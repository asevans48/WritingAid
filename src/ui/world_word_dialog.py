"""Dialog for AI-powered world-appropriate word suggestions.

Runs a multi-step pipeline:
1. Identify the relevant scene context around the selection
2. Detect which character is speaking/thinking from the text
3. Gather worldbuilding + character details (or infer personality from text)
4. Generate voice-appropriate, world-appropriate word suggestions
"""

import re
from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem,
    QProgressBar, QMessageBox, QComboBox,
    QWidget, QScrollArea, QFrame, QLineEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal


def _parse_suggestions(response: str) -> list:
    """Parse numbered suggestions from an LLM response."""
    suggestions = []
    current_word = None
    current_explanation = []

    for line in response.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        match = re.match(
            r'^\d+[\.\)]\s*\*{0,2}(.+?)\*{0,2}\s*[-\u2013\u2014:]\s*(.+)$', line
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


class _ThesaurusPipelineWorker(QThread):
    """Runs the full AI thesaurus pipeline in one background thread.

    Steps:
    1. Identify speaker from the passage text
    2. If unknown character, infer personality traits from the passage
    3. Generate word suggestions using worldbuilding + character voice
    """

    progress = pyqtSignal(str)          # Status message for each step
    speaker_detected = pyqtSignal(str, str, str)  # (name, reason, personality_summary)
    finished = pyqtSignal(list)         # List of (suggestion, explanation)
    error = pyqtSignal(str)

    def __init__(
        self, llm_client, selected_text: str, passage: str,
        characters_info: str, known_characters: list,
        worldbuilding_ctx: str, user_description: str,
        manual_character=None, is_narrator: bool = False,
        chapter_number: int = 0,
        thesaurus_context: str = "",
        refinement_history: list = None
    ):
        super().__init__()
        self.llm = llm_client
        self.selected_text = selected_text
        self.passage = passage
        self.characters_info = characters_info
        self.known_characters = known_characters
        self.worldbuilding_ctx = worldbuilding_ctx
        self.user_description = user_description
        self.manual_character = manual_character
        self.is_narrator = is_narrator
        self.chapter_number = chapter_number
        self.thesaurus_context = thesaurus_context  # POS-aware thesaurus data
        self.refinement_history = refinement_history or []
        self.previous_suggestions = []  # Filled on refinement runs

    def run(self):
        try:
            self.progress.emit("Generating suggestions...")

            # Build character voice context
            if self.manual_character:
                char_name = self.manual_character.name
                voice_profile = self._build_voice_from_character(self.manual_character)
                self.speaker_detected.emit(char_name, "Manually selected", voice_profile)
            elif self.is_narrator:
                char_name = "Narrator"
                voice_profile = ""
                self.speaker_detected.emit("Narrator", "Narrator mode", "")
            else:
                # Auto-detect: done in a SINGLE call alongside suggestion generation
                char_name = None
                voice_profile = None

            # Single LLM call that handles detection + suggestions together
            suggestions = self._generate_suggestions(char_name, voice_profile)
            self.finished.emit(suggestions)

        except Exception as e:
            error_msg = str(e)
            # Friendlier message for Metal OOM
            if "OutOfMemory" in error_msg or "Insufficient Memory" in error_msg:
                error_msg = (
                    "Out of GPU memory. The local model may be too large.\n\n"
                    "Try:\n"
                    "- Closing other apps to free memory\n"
                    "- Using a smaller model (e.g. 4B instead of 27B) in Settings\n"
                    "- Selecting a specific character instead of Auto-detect"
                )
            self.error.emit(error_msg)

    def _build_voice_from_character(self, character) -> str:
        """Build a voice profile from a known Character object."""
        parts = []
        if getattr(character, 'personality', ''):
            parts.append(f"Personality: {character.personality[:200]}")
        if getattr(character, 'personality_traits', None):
            parts.append(f"Traits: {', '.join(character.personality_traits)}")
        if getattr(character, 'speaking_style', ''):
            parts.append(f"Speaking style: {character.speaking_style}")
        if getattr(character, 'motivations', ''):
            parts.append(f"Motivations: {character.motivations[:150]}")
        if getattr(character, 'fears', ''):
            parts.append(f"Fears: {character.fears[:100]}")
        if getattr(character, 'emotional_baseline', ''):
            parts.append(f"Emotional baseline: {character.emotional_baseline}")
        if getattr(character, 'personality_arc', None):
            arc = character.personality_arc
            if arc and self.chapter_number:
                closest = min(arc, key=lambda s: abs(s.chapter_number - self.chapter_number))
                if closest.emotional_state:
                    parts.append(f"Current emotional state: {closest.emotional_state}")
                if closest.growth_notes:
                    parts.append(f"Recent development: {closest.growth_notes[:150]}")
            elif arc:
                latest = arc[-1]
                if latest.emotional_state:
                    parts.append(f"Emotional state: {latest.emotional_state}")
        return "\n".join(parts)

    def _generate_suggestions(self, char_name, voice_profile) -> list:
        """Generate word suggestions in a single LLM call.

        If char_name is None (auto-detect mode), the prompt asks the model
        to identify the speaker AND generate suggestions in one pass — saving
        GPU memory by avoiding multiple model loads.
        """
        auto_detect = char_name is None
        system_prompt = (
            "You are a creative writing assistant specializing in character-voice-aware "
            "and worldbuilding-aware word choice.\n\n"
            "Rules:\n"
        )

        if auto_detect:
            system_prompt += (
                "- FIRST: Read the passage and identify who is speaking or whose "
                "perspective the bracketed text belongs to. State the name and "
                "your evidence in one line: SPEAKER: name — reason\n"
                "- The speaker may be a MINOR character not in the known characters list\n"
                "- Do NOT default to a major character unless the passage proves it\n"
                "- Then infer that character's vocabulary, education, and emotional state "
                "from how they speak/act in the passage\n"
            )

        system_prompt += (
            "- Suggest 5-8 replacement options, numbered\n"
            "- Each suggestion: a single word or short phrase (1-4 words)\n"
            "- Format: NUMBER. SUGGESTION \u2014 BRIEF EXPLANATION\n"
            "- Suggestions MUST fit the character's vocabulary, education level, "
            "emotional state, and social class\n"
            "- Pay close attention to the FULL surrounding text — understand what is "
            "happening emotionally in the scene (e.g. a character shifting from hostile "
            "to friendly, or building tension)\n"
            "- Draw from the world's cultures and languages where relevant\n"
            "- Range from subtle/grounded to creative/inventive"
        )

        if not auto_detect and voice_profile and char_name != "Narrator":
            system_prompt += (
                f"\n\nCHARACTER VOICE — {char_name}:\n{voice_profile}\n\n"
                "Word choices must sound like this character. A street urchin "
                "uses different words than a scholar."
            )
        elif not auto_detect and char_name == "Narrator":
            system_prompt += (
                "\n\nThis is narrator text (not dialogue). "
                "Match the narrative voice and tone of the surrounding prose."
            )

        if self.worldbuilding_ctx:
            system_prompt += f"\n\nWORLDBUILDING:\n{self.worldbuilding_ctx}"

        prompt_parts = []

        # Refinement instructions go FIRST so they are the most prominent
        if self.refinement_history:
            reject_block = (
                "CRITICAL — THE AUTHOR HAS GIVEN SPECIFIC FEEDBACK. "
                "You MUST follow these instructions and generate COMPLETELY DIFFERENT "
                "suggestions from before:\n"
            )
            for entry in self.refinement_history:
                reject_block += f"  \u2022 {entry}\n"
            if self.previous_suggestions:
                rejected = ', '.join(f'"{s}"' for s in self.previous_suggestions)
                reject_block += (
                    f"\nDo NOT suggest any of these again: {rejected}\n"
                    "Every suggestion must be a NEW word not in the list above."
                )
            prompt_parts.append(reject_block)

        prompt_parts.append(f'Replace the word/phrase: "{self.selected_text}"')
        if auto_detect:
            if self.characters_info:
                prompt_parts.append(
                    "Known characters (reference only — speaker may not be any of these):\n"
                    + self.characters_info
                )
            prompt_parts.append(
                "First identify the speaker from the passage, then suggest replacements "
                "in that character's voice."
            )
        else:
            prompt_parts.append(f"Character: {char_name}")

        # Include surrounding text — use the full passage for emotional context
        if self.passage:
            sel_pos = self.passage.find(f"[{self.selected_text}]")
            if sel_pos >= 0:
                start = max(0, sel_pos - 800)
                end = min(len(self.passage), sel_pos + len(self.selected_text) + 400)
                snippet = self.passage[start:end]
            else:
                snippet = self.passage[-1000:]
            prompt_parts.append(
                f"SCENE CONTEXT (read carefully for emotional tone and what is happening):\n"
                f"{snippet}"
            )

        # Include POS-aware thesaurus data
        if self.thesaurus_context:
            prompt_parts.append(
                f"THESAURUS REFERENCE (part-of-speech aware):\n{self.thesaurus_context}\n"
                "You may adapt these or suggest entirely different words."
            )

        if self.user_description:
            prompt_parts.append(f"Author's notes: {self.user_description}")

        prompt_parts.append(
            "Suggest replacements that fit this character's voice, "
            "the emotional beat of the scene, and this world."
        )

        response = self.llm.generate_text(
            prompt="\n\n".join(prompt_parts),
            system_prompt=system_prompt,
            max_tokens=1500, temperature=0.8,
            task_type="world_word"
        )

        # If auto-detect, extract the SPEAKER line before parsing suggestions
        if auto_detect:
            for line in response.strip().split('\n'):
                line = line.strip()
                if line.upper().startswith("SPEAKER:"):
                    speaker_info = line[len("SPEAKER:"):].strip()
                    # Split on — or - for name and reason
                    if '\u2014' in speaker_info:
                        name, reason = speaker_info.split('\u2014', 1)
                    elif ' - ' in speaker_info:
                        name, reason = speaker_info.split(' - ', 1)
                    else:
                        name, reason = speaker_info, ""
                    self.speaker_detected.emit(
                        name.strip(), reason.strip(), ""
                    )
                    break

        return _parse_suggestions(response)


class WorldWordDialog(QDialog):
    """Dialog for finding world-appropriate word replacements with POV awareness."""

    def __init__(self, selected_text: str, project=None, parent=None,
                 surrounding_context: tuple = None,
                 chapter_content: str = "", chapter=None):
        super().__init__(parent)
        self.selected_text = selected_text
        self.project = project
        self.surrounding_before = surrounding_context[0] if surrounding_context else ""
        self.surrounding_after = surrounding_context[1] if surrounding_context else ""
        self.chapter_content = chapter_content
        self.chapter = chapter
        self.chosen_replacement: Optional[str] = None
        self.pipeline_worker: Optional[_ThesaurusPipelineWorker] = None
        self.suggestions: List[tuple] = []
        self._refinement_history: List[str] = []

        self._init_ui()
        self._init_llm()

    def _init_ui(self):
        self.setWindowTitle("AI Thesaurus")
        self.setMinimumSize(480, 400)
        self.resize(600, 560)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Scroll area wraps all content for small screens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_widget = QWidget()
        main_layout = QVBoxLayout(scroll_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        # Header + selected word (compact)
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<b>AI Thesaurus</b>"))
        header_layout.addStretch()
        self.selected_label = QLabel(f'Replacing: "<b>{self.selected_text}</b>"')
        self.selected_label.setWordWrap(True)
        self.selected_label.setStyleSheet("font-size: 11px;")
        header_layout.addWidget(self.selected_label)
        main_layout.addLayout(header_layout)

        # Voice selector + description side by side for compactness
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        # Voice selector
        voice_widget = QWidget()
        voice_layout = QVBoxLayout(voice_widget)
        voice_layout.setContentsMargins(0, 0, 0, 0)
        voice_layout.setSpacing(2)
        voice_layout.addWidget(QLabel("Whose voice:"))
        self.char_combo = QComboBox()
        self.char_combo.addItem("Auto-detect from text", "auto")
        self.char_combo.addItem("Narrator", "narrator")
        if self.project and hasattr(self.project, 'characters'):
            for c in self.project.characters:
                self.char_combo.addItem(f"{c.name} ({c.character_type})", c.id)
        voice_layout.addWidget(self.char_combo)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #6b7280; font-size: 10px; font-style: italic;")
        self.status_label.setVisible(False)
        voice_layout.addWidget(self.status_label)
        voice_layout.addStretch()
        top_row.addWidget(voice_widget)

        # Description input
        desc_widget = QWidget()
        desc_layout = QVBoxLayout(desc_widget)
        desc_layout.setContentsMargins(0, 0, 0, 0)
        desc_layout.setSpacing(2)
        desc_layout.addWidget(QLabel("What are you looking for? (optional)"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "e.g.: a word for 'magic' in this culture\n"
            "e.g.: something archaic and foreboding"
        )
        self.description_edit.setMaximumHeight(55)
        desc_layout.addWidget(self.description_edit)
        top_row.addWidget(desc_widget, stretch=1)

        main_layout.addLayout(top_row)

        # Generate + progress
        gen_layout = QHBoxLayout()
        self.generate_btn = QPushButton("Generate Suggestions")
        self.generate_btn.setStyleSheet("font-weight: bold; padding: 5px 14px;")
        self.generate_btn.clicked.connect(self._generate)
        gen_layout.addWidget(self.generate_btn)
        gen_layout.addStretch()
        main_layout.addLayout(gen_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(4)
        main_layout.addWidget(self.progress_bar)

        # Suggestions + synonyms side by side
        sug_row = QHBoxLayout()
        sug_row.setSpacing(6)

        # Main suggestion list
        sug_widget = QWidget()
        sug_layout = QVBoxLayout(sug_widget)
        sug_layout.setContentsMargins(0, 0, 0, 0)
        sug_layout.setSpacing(2)
        sug_layout.addWidget(QLabel("<b>Suggestions</b>"))
        self.suggestion_list = QListWidget()
        self.suggestion_list.currentRowChanged.connect(self._on_suggestion_selected)
        sug_layout.addWidget(self.suggestion_list)
        self.explanation_label = QLabel("")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setStyleSheet(
            "color: #4b5563; font-style: italic; font-size: 10px;"
        )
        self.explanation_label.setMaximumHeight(40)
        sug_layout.addWidget(self.explanation_label)
        sug_row.addWidget(sug_widget, stretch=2)

        # Synonyms panel (for selected suggestion)
        syn_widget = QWidget()
        syn_layout = QVBoxLayout(syn_widget)
        syn_layout.setContentsMargins(0, 0, 0, 0)
        syn_layout.setSpacing(2)
        self.synonyms_label = QLabel("Synonyms")
        self.synonyms_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        syn_layout.addWidget(self.synonyms_label)
        self.synonyms_list = QListWidget()
        self.synonyms_list.setStyleSheet("font-size: 11px;")
        self.synonyms_list.itemDoubleClicked.connect(self._use_synonym)
        syn_layout.addWidget(self.synonyms_list)
        sug_row.addWidget(syn_widget, stretch=1)

        main_layout.addLayout(sug_row, stretch=1)

        # Refinement chat
        refine_layout = QHBoxLayout()
        refine_layout.setSpacing(4)
        self.refine_edit = QLineEdit()
        self.refine_edit.setPlaceholderText("Refine: 'more formal', 'this character wouldn't say that'...")
        self.refine_edit.setStyleSheet("font-size: 11px; padding: 3px;")
        self.refine_edit.returnPressed.connect(self._refine)
        refine_layout.addWidget(self.refine_edit)
        self.refine_btn = QPushButton("Refine")
        self.refine_btn.setStyleSheet("font-size: 11px; padding: 3px 10px;")
        self.refine_btn.clicked.connect(self._refine)
        refine_layout.addWidget(self.refine_btn)
        main_layout.addLayout(refine_layout)

        scroll.setWidget(scroll_widget)
        outer_layout.addWidget(scroll)

        # Bottom buttons (outside scroll — always visible)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(10, 6, 10, 10)
        btn_layout.addStretch()

        self.use_btn = QPushButton("Use Selected")
        self.use_btn.setEnabled(False)
        self.use_btn.setDefault(True)
        self.use_btn.clicked.connect(self._use_selected)
        btn_layout.addWidget(self.use_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        outer_layout.addLayout(btn_layout)

    def _init_llm(self):
        """Initialize the LLM client, respecting local model preferences."""
        self.llm_client = None
        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig

            config = get_ai_config()
            if config.is_ai_disabled():
                return

            settings = config.get_settings()
            prefer_local = settings.get("prefer_local_model", False)
            enable_local = settings.get("enable_local_models", False)
            local_model_id = settings.get("local_model_id", "")

            if prefer_local and enable_local and local_model_id:
                is_mlx_model = "mlx" in local_model_id.lower()
                hf_config = HuggingFaceConfig(
                    model_id=local_model_id, use_local=True,
                    device=settings.get("local_model_device", "auto"),
                    quantization=settings.get("local_model_quantization", "none")
                        if settings.get("local_model_quantization") != "none" else None,
                    trust_remote_code=settings.get("local_model_trust_remote_code", False)
                )
                provider = LLMProvider.MLX_LOCAL if is_mlx_model else LLMProvider.HUGGINGFACE_LOCAL
                self.llm_client = LLMClient(provider=provider, hf_config=hf_config)
            else:
                provider_name = settings.get("default_llm", "claude").lower()
                api_key = config.get_api_key(provider_name)
                if api_key:
                    provider_enum = {
                        "claude": LLMProvider.CLAUDE, "chatgpt": LLMProvider.CHATGPT,
                        "openai": LLMProvider.CHATGPT, "gemini": LLMProvider.GEMINI,
                    }.get(provider_name, LLMProvider.CLAUDE)
                    self.llm_client = LLMClient(
                        provider=provider_enum, api_key=api_key,
                        model=config.get_model(provider_name)
                    )
                elif enable_local and local_model_id:
                    is_mlx_model = "mlx" in local_model_id.lower()
                    hf_config = HuggingFaceConfig(
                        model_id=local_model_id, use_local=True,
                        device=settings.get("local_model_device", "auto"),
                        quantization=settings.get("local_model_quantization", "none")
                            if settings.get("local_model_quantization") != "none" else None,
                        trust_remote_code=settings.get("local_model_trust_remote_code", False)
                    )
                    provider = LLMProvider.MLX_LOCAL if is_mlx_model else LLMProvider.HUGGINGFACE_LOCAL
                    self.llm_client = LLMClient(provider=provider, hf_config=hf_config)
        except Exception as e:
            print(f"World word dialog: LLM init failed: {e}")

    # --- Passage builder ---

    def _build_passage(self) -> str:
        """Build a passage around the selection from chapter content.

        Uses ~800 chars before and ~300 after — enough for speaker detection
        and emotional context without blowing up the prompt for large models.
        """
        if self.chapter_content:
            sel_pos = self.chapter_content.find(self.selected_text)
            if sel_pos >= 0:
                start = max(0, sel_pos - 800)
                end = min(len(self.chapter_content),
                          sel_pos + len(self.selected_text) + 300)
                before = self.chapter_content[start:sel_pos]
                after = self.chapter_content[sel_pos + len(self.selected_text):end]
                return f"{before}[{self.selected_text}]{after}"

        # Fallback to surrounding context
        passage = ""
        if self.surrounding_before:
            passage += self.surrounding_before[-600:]
        passage += f" [{self.selected_text}] "
        if self.surrounding_after:
            passage += self.surrounding_after[:300]
        return passage

    def _build_characters_info(self) -> str:
        """Build a brief summary of known characters for reference."""
        if not self.project or not hasattr(self.project, 'characters'):
            return ""
        parts = []
        for c in self.project.characters:
            info = f"- {c.name} ({c.character_type})"
            if c.personality:
                info += f": {c.personality[:80]}"
            if getattr(c, 'speaking_style', None):
                info += f" | speaks: {c.speaking_style[:60]}"
            parts.append(info)
        return "\n".join(parts)

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
            cp = []
            for c in wb.cultures[:6]:
                info = f"- {c.name}"
                if hasattr(c, 'description') and c.description:
                    info += f": {c.description[:150]}"
                if hasattr(c, 'languages') and c.languages:
                    info += f" (Languages: {c.languages[:100]})"
                cp.append(info)
            parts.append("CULTURES:\n" + "\n".join(cp))
        if wb.magic_systems:
            mp = []
            for m in wb.magic_systems[:4]:
                info = f"- {m.name}"
                if hasattr(m, 'description') and m.description:
                    info += f": {m.description[:150]}"
                mp.append(info)
            parts.append("MAGIC SYSTEMS:\n" + "\n".join(mp))
        if wb.factions:
            fp = []
            for f in wb.factions[:6]:
                info = f"- {f.name}"
                if hasattr(f, 'description') and f.description:
                    info += f": {f.description[:120]}"
                fp.append(info)
            parts.append("FACTIONS:\n" + "\n".join(fp))
        if wb.places:
            pp = []
            for p in wb.places[:6]:
                info = f"- {p.name}"
                if hasattr(p, 'description') and p.description:
                    info += f": {p.description[:120]}"
                pp.append(info)
            parts.append("PLACES:\n" + "\n".join(pp))
        if wb.custom_sections:
            for key, val in list(wb.custom_sections.items())[:3]:
                if val:
                    parts.append(f"{key.upper()}: {val[:300]}")
        return "\n\n".join(parts)

    def _build_thesaurus_context(self) -> str:
        """Build POS-aware thesaurus context for the selected word."""
        try:
            clean = re.sub(r'^[^\w]+|[^\w]+$', '', self.selected_text)
            lookup = clean.split()[0] if ' ' in clean else clean
            if not lookup or len(lookup) > 30:
                return ""

            # Try WordNet directly for POS-aware data
            try:
                from nltk.corpus import wordnet
                pos_map = {
                    wordnet.NOUN: "noun",
                    wordnet.VERB: "verb",
                    wordnet.ADJ: "adjective",
                    wordnet.ADV: "adverb",
                }
                parts = []
                for pos_code, pos_name in pos_map.items():
                    synsets = wordnet.synsets(lookup, pos=pos_code)
                    if not synsets:
                        continue
                    syns = set()
                    for ss in synsets[:3]:
                        definition = ss.definition()
                        for lemma in ss.lemmas():
                            name = lemma.name().replace('_', ' ')
                            if name.lower() != lookup.lower():
                                syns.add(name.lower())
                    if syns:
                        syn_list = ', '.join(sorted(syns)[:8])
                        # Include definition of first synset for usage context
                        defn = synsets[0].definition()
                        parts.append(
                            f"As {pos_name} (\"{defn}\"): {syn_list}"
                        )
                if parts:
                    return "\n".join(parts)
            except Exception:
                pass

            # Fallback: plain synonyms/antonyms without POS
            from src.utils.thesaurus import get_synonyms, get_antonyms
            syns = get_synonyms(lookup, max_results=12)
            ants = get_antonyms(lookup, max_results=6)
            parts = []
            if syns:
                parts.append(f"Synonyms: {', '.join(syns)}")
            if ants:
                parts.append(f"Antonyms: {', '.join(ants)}")
            return "\n".join(parts)
        except Exception:
            return ""

    def _refine(self):
        """Refine suggestions with a follow-up instruction."""
        instruction = self.refine_edit.text().strip()
        if not instruction:
            return
        self._refinement_history.append(instruction)
        self.refine_edit.clear()
        # Store current suggestions so the pipeline can tell the AI to avoid them
        self._previous_suggestions = [s[0] for s in self.suggestions]
        # Re-run the pipeline with the refinement context
        self._generate()

    def _get_manual_character(self):
        """Get the manually selected Character object, or None."""
        data = self.char_combo.currentData()
        if data in ("auto", "narrator", None):
            return None
        if self.project and hasattr(self.project, 'characters'):
            return next((c for c in self.project.characters if c.id == data), None)
        return None

    # --- Generation ---

    def _generate(self):
        """Launch the full pipeline."""
        if not self.llm_client:
            QMessageBox.warning(
                self, "AI Not Available",
                "No AI provider is configured.\n\n"
                "Configure an LLM in Settings > AI Configuration."
            )
            return

        # Show progress
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Working...")
        self.progress_bar.setVisible(True)
        self.suggestion_list.clear()
        self.explanation_label.setText("")
        self.synonyms_label.setVisible(False)
        self.synonyms_list.setVisible(False)
        self.use_btn.setEnabled(False)
        self.status_label.setText("Starting pipeline...")
        self.status_label.setVisible(True)

        # Gather inputs
        passage = self._build_passage()
        chars_info = self._build_characters_info()
        known_chars = list(self.project.characters) if self.project and hasattr(self.project, 'characters') else []
        wb_ctx = self._build_worldbuilding_context()
        user_desc = self.description_edit.toPlainText().strip()
        manual_char = self._get_manual_character()
        is_narrator = self.char_combo.currentData() == "narrator"
        ch_num = getattr(self.chapter, 'number', 0) if self.chapter else 0

        # Build POS-aware thesaurus context
        thesaurus_ctx = self._build_thesaurus_context()

        # Get previous suggestions to exclude on refinement runs
        prev_suggestions = getattr(self, '_previous_suggestions', [])

        self.pipeline_worker = _ThesaurusPipelineWorker(
            llm_client=self.llm_client,
            selected_text=self.selected_text,
            passage=passage,
            characters_info=chars_info,
            known_characters=known_chars,
            worldbuilding_ctx=wb_ctx,
            user_description=user_desc,
            manual_character=manual_char,
            is_narrator=is_narrator,
            chapter_number=ch_num,
            thesaurus_context=thesaurus_ctx,
            refinement_history=list(self._refinement_history)
        )
        self.pipeline_worker.previous_suggestions = prev_suggestions
        self.pipeline_worker.progress.connect(self._on_pipeline_progress)
        self.pipeline_worker.speaker_detected.connect(self._on_speaker_detected)
        self.pipeline_worker.finished.connect(self._on_suggestions_ready)
        self.pipeline_worker.error.connect(self._on_error)
        self.pipeline_worker.start()

    def _on_pipeline_progress(self, message: str):
        """Update status during pipeline execution."""
        self.status_label.setText(message)

    def _on_speaker_detected(self, name: str, reason: str, voice_profile: str):
        """Show who was detected as the speaker."""
        parts = [f"Voice: <b>{name}</b>"]
        if reason:
            parts.append(f" \u2014 {reason}")
        self.status_label.setText("".join(parts))

    def _on_suggestions_ready(self, suggestions: list):
        """Handle pipeline completion."""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generate Suggestions")
        self.suggestions = suggestions

        if not suggestions:
            self.suggestion_list.addItem(
                "(no suggestions \u2014 try adding more detail)"
            )
            return

        for word, explanation in suggestions:
            item = QListWidgetItem(word)
            item.setData(Qt.ItemDataRole.UserRole, explanation)
            self.suggestion_list.addItem(item)
        self.suggestion_list.setCurrentRow(0)

    def _on_error(self, error_msg: str):
        """Handle pipeline error."""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generate Suggestions")
        self.status_label.setText(f"Error: {error_msg}")
        QMessageBox.warning(self, "Error", f"Pipeline failed:\n\n{error_msg}")

    def _on_suggestion_selected(self, row: int):
        """Show explanation and offline synonyms for the selected suggestion."""
        if row < 0 or row >= len(self.suggestions):
            self.explanation_label.setText("")
            self.synonyms_list.clear()
            self.use_btn.setEnabled(False)
            return

        word, explanation = self.suggestions[row]
        self.explanation_label.setText(explanation)
        self.use_btn.setEnabled(True)

        # Show offline thesaurus synonyms for the selected AI suggestion
        self.synonyms_list.clear()
        try:
            from src.utils.thesaurus import get_synonyms
            clean = re.sub(r'^[^\w]+|[^\w]+$', '', word)
            lookup = clean.split()[0] if ' ' in clean else clean
            syns = get_synonyms(lookup, max_results=10)
            if syns:
                self.synonyms_label.setText(f'Synonyms for "{lookup}" (double-click to use)')
                for s in syns:
                    self.synonyms_list.addItem(s)
            else:
                self.synonyms_label.setText("No synonyms found")
        except Exception:
            self.synonyms_label.setText("Thesaurus unavailable")

    def _use_synonym(self, item):
        """Accept a synonym as the replacement."""
        self.chosen_replacement = item.text()
        self.accept()

    def _use_selected(self):
        """Accept the selected suggestion."""
        row = self.suggestion_list.currentRow()
        if 0 <= row < len(self.suggestions):
            self.chosen_replacement = self.suggestions[row][0]
            self.accept()

    def get_replacement(self) -> Optional[str]:
        """Get the chosen replacement word."""
        return self.chosen_replacement
