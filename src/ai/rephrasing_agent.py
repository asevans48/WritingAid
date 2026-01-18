"""Rephrasing agent for text rewriting with multiple options."""

import re
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.models.project import WriterProject


# Global NLP cache for spaCy and WordNet to avoid reloading
class _NLPCache:
    """Singleton cache for NLP resources (spaCy, WordNet) across agent instances."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._spacy_nlp = None
            cls._instance._spacy_available = None
            cls._instance._wordnet = None
            cls._instance._wordnet_available = None
            cls._instance._nltk_ready = False
        return cls._instance

    def get_spacy(self):
        """Get cached spaCy model, initializing if needed."""
        if self._spacy_available is not None:
            return self._spacy_nlp if self._spacy_available else None

        try:
            import spacy
            try:
                self._spacy_nlp = spacy.load("en_core_web_sm")
                self._spacy_available = True
                print("spaCy initialized with en_core_web_sm model (cached)")
            except OSError:
                print("spaCy model not found, attempting to download en_core_web_sm...")
                try:
                    from spacy.cli import download
                    download("en_core_web_sm")
                    self._spacy_nlp = spacy.load("en_core_web_sm")
                    self._spacy_available = True
                    print("spaCy en_core_web_sm model downloaded and loaded (cached)")
                except Exception as e:
                    print(f"Failed to download spaCy model: {e}")
                    self._spacy_available = False
        except ImportError:
            print("spaCy not installed. Install with: pip install spacy")
            self._spacy_available = False

        return self._spacy_nlp if self._spacy_available else None

    def is_spacy_available(self) -> bool:
        """Check if spaCy is available (triggers init if not checked)."""
        if self._spacy_available is None:
            self.get_spacy()
        return self._spacy_available or False

    def get_wordnet(self):
        """Get cached WordNet, initializing if needed."""
        if self._wordnet_available is not None:
            return self._wordnet if self._wordnet_available else None

        try:
            import nltk
            from nltk.corpus import wordnet
            try:
                nltk.data.find('corpora/wordnet')
            except LookupError:
                nltk.download('wordnet', quiet=True)
                nltk.download('omw-1.4', quiet=True)
            self._wordnet = wordnet
            self._wordnet_available = True
        except ImportError:
            self._wordnet_available = False

        return self._wordnet if self._wordnet_available else None

    def ensure_nltk_ready(self):
        """Ensure NLTK tokenizers and taggers are downloaded."""
        if self._nltk_ready:
            return True
        try:
            import nltk
            try:
                nltk.data.find('tokenizers/punkt')
            except LookupError:
                nltk.download('punkt', quiet=True)
            try:
                nltk.data.find('tokenizers/punkt_tab')
            except LookupError:
                nltk.download('punkt_tab', quiet=True)
            try:
                nltk.data.find('taggers/averaged_perceptron_tagger')
            except LookupError:
                nltk.download('averaged_perceptron_tagger', quiet=True)
            self._nltk_ready = True
            return True
        except Exception:
            return False


# Global NLP cache instance
_nlp_cache = _NLPCache()


# Global model cache to persist models across agent instances
class _LocalModelCache:
    """Singleton cache for local models to avoid reloading on each use."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._tokenizer = None
            cls._instance._model_id = None
            cls._instance._device = None
        return cls._instance

    def get_model(self, model_id: str):
        """Get cached model if it matches the requested model_id."""
        if self._model is not None and self._model_id == model_id:
            return self._model, self._tokenizer, self._device
        return None, None, None

    def set_model(self, model_id: str, model, tokenizer, device: str):
        """Cache a loaded model."""
        # Unload previous model if different
        if self._model is not None and self._model_id != model_id:
            self._unload_model()

        self._model = model
        self._tokenizer = tokenizer
        self._model_id = model_id
        self._device = device
        print(f"Model cached: {model_id} on {device}")

    def _unload_model(self):
        """Unload the current model from memory."""
        if self._model is not None:
            print(f"Unloading previous model: {self._model_id}")
            try:
                import torch
                del self._model
                del self._tokenizer
                self._model = None
                self._tokenizer = None
                self._model_id = None
                self._device = None
                # Clear CUDA cache if available
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as e:
                print(f"Error unloading model: {e}")

    def is_loaded(self, model_id: str = None) -> bool:
        """Check if a model is loaded (optionally check specific model_id)."""
        if model_id:
            return self._model is not None and self._model_id == model_id
        return self._model is not None

    def get_loaded_model_id(self) -> Optional[str]:
        """Get the ID of the currently loaded model."""
        return self._model_id

    def unload(self):
        """Explicitly unload the model."""
        self._unload_model()


# Global instance
_model_cache = _LocalModelCache()


class RephraseStyle(Enum):
    """Available rephrasing styles (structural/writing approach)."""
    CONCISE = "concise"
    ELABORATE = "elaborate"
    FORMAL = "formal"
    CASUAL = "casual"
    POETIC = "poetic"
    ACTIVE_VOICE = "active_voice"
    CLEARER = "clearer"


class RephraseTone(Enum):
    """Available rephrasing tones (emotional quality)."""
    NEUTRAL = "neutral"
    DARK = "dark"
    DRAMATIC = "dramatic"
    HOPEFUL = "hopeful"
    MELANCHOLIC = "melancholic"
    TENSE = "tense"
    WHIMSICAL = "whimsical"


@dataclass
class RephraseOption:
    """A single rephrasing option."""
    text: str
    style: str
    tone: str
    explanation: str


@dataclass
class RephraseResult:
    """Result of rephrasing operation."""
    original: str
    options: List[RephraseOption]
    model_used: str
    cost_estimate: float


class RephrasingAgent:
    """Agent for generating multiple rephrasing options for text.

    Supports both cloud LLMs and local small language models (SLMs).
    """

    REPHRASE_SYSTEM = """You are a skilled editor helping an author rephrase their writing.
Your job is to provide several alternative phrasings while preserving the original meaning.

Guidelines:
- Maintain the original intent and key information
- Apply the requested style (structural approach) and tone (emotional quality)
- Keep the same tense unless specifically asked to change it
- Preserve any character names, proper nouns, or specific terminology
- Make the text flow naturally

For each option, briefly explain what makes it different from the original."""

    # Style prompts (structural/writing approach)
    STYLE_PROMPTS = {
        RephraseStyle.CONCISE: "concise and tight",
        RephraseStyle.ELABORATE: "more detailed and descriptive",
        RephraseStyle.FORMAL: "formal and professional",
        RephraseStyle.CASUAL: "casual and conversational",
        RephraseStyle.POETIC: "poetic and lyrical",
        RephraseStyle.ACTIVE_VOICE: "using active voice",
        RephraseStyle.CLEARER: "clearer and easier to understand",
    }

    # Tone prompts (emotional quality)
    TONE_PROMPTS = {
        RephraseTone.NEUTRAL: "",  # No tone modifier
        RephraseTone.DARK: "dark and ominous",
        RephraseTone.DRAMATIC: "dramatic and impactful",
        RephraseTone.HOPEFUL: "hopeful and optimistic",
        RephraseTone.MELANCHOLIC: "melancholic and wistful",
        RephraseTone.TENSE: "tense and suspenseful",
        RephraseTone.WHIMSICAL: "whimsical and playful",
    }

    def __init__(
        self,
        llm_client: Optional['LLMClient'] = None,
        project: Optional['WriterProject'] = None,
        use_local_model: bool = False,
        local_model_id: Optional[str] = None,
        use_python_libraries: bool = False
    ):
        """Initialize rephrasing agent.

        Args:
            llm_client: LLM client for API calls
            project: Project for context
            use_local_model: Whether to use local SLM instead of cloud API
            local_model_id: Optional model ID to use for local model (from settings)
            use_python_libraries: Whether to use nlpaug/nltk instead of any AI
        """
        self.llm = llm_client
        self.project = project
        self.use_local_model = use_local_model
        self.local_model_id = local_model_id
        self.use_python_libraries = use_python_libraries
        self._local_model = None
        self._local_tokenizer = None
        self._device = None
        self._nlpaug_initialized = False
        self._spacy_nlp = None
        self._spacy_available = None  # None = not checked, True/False = checked

    def _init_local_model(self):
        """Initialize local small language model.

        Uses a global cache to keep models loaded in memory across agent instances.
        Only reloads if a different model is requested.
        """
        # Use model from settings, or fall back to default
        model_id = self.local_model_id or "microsoft/Phi-3-mini-4k-instruct"

        # Check if model is already cached
        cached_model, cached_tokenizer, cached_device = _model_cache.get_model(model_id)
        if cached_model is not None:
            print(f"Using cached model: {model_id} on {cached_device}")
            self._local_model = cached_model
            self._local_tokenizer = cached_tokenizer
            self._device = cached_device
            return

        # Check if instance already has this model loaded
        if self._local_model is not None:
            return

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch

            print(f"Loading local model: {model_id}")

            tokenizer = AutoTokenizer.from_pretrained(
                model_id,
                trust_remote_code=True
            )

            # Try CUDA first, fall back to CPU if it fails
            device = "cpu"
            model = None
            cuda_available = torch.cuda.is_available()
            print(f"CUDA available (torch.cuda.is_available()): {cuda_available}")

            # Check if PyTorch was built with CUDA support
            cuda_built = torch.backends.cuda.is_built() if hasattr(torch.backends, 'cuda') else False
            print(f"PyTorch built with CUDA: {cuda_built}")
            print(f"PyTorch version: {torch.__version__}")

            if not cuda_built:
                print("WARNING: PyTorch was installed without CUDA support!")
                print("To enable GPU acceleration, reinstall PyTorch with CUDA:")
                print("  pip uninstall torch torchvision torchaudio")
                print("")
                print("Then install with your CUDA version (check with 'nvidia-smi'):")
                print("  CUDA 13.x: pip install torch --index-url https://download.pytorch.org/whl/cu131")
                print("  CUDA 12.x: pip install torch --index-url https://download.pytorch.org/whl/cu121")
                print("  CUDA 11.8: pip install torch --index-url https://download.pytorch.org/whl/cu118")
                print("")
                print("Check https://pytorch.org/get-started/locally/ for the latest wheel URLs.")

            if cuda_available:
                try:
                    print(f"CUDA device count: {torch.cuda.device_count()}")
                    print(f"CUDA device name: {torch.cuda.get_device_name(0)}")
                    print(f"CUDA version: {torch.version.cuda}")
                    print("Attempting to load model on CUDA...")
                    model = AutoModelForCausalLM.from_pretrained(
                        model_id,
                        torch_dtype=torch.float16,
                        device_map="auto",
                        trust_remote_code=True
                    )
                    device = "cuda"
                    print("Model loaded successfully on CUDA")
                except Exception as cuda_err:
                    # Catch ALL exceptions during CUDA loading, not just specific ones
                    print(f"CUDA loading failed: {type(cuda_err).__name__}: {cuda_err}")
                    print("Falling back to CPU...")
                    # Clear CUDA cache before falling back
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    model = None

            # Load on CPU if CUDA not available or failed
            if model is None:
                print("Loading model on CPU...")
                model = AutoModelForCausalLM.from_pretrained(
                    model_id,
                    torch_dtype=torch.float32,
                    trust_remote_code=True
                )
                model = model.to("cpu")
                device = "cpu"

            # Store in instance
            self._local_model = model
            self._local_tokenizer = tokenizer
            self._device = device

            # Cache for future use
            _model_cache.set_model(model_id, model, tokenizer, device)
            print(f"Local model loaded on {device}")

        except ImportError:
            raise ImportError(
                "Local model requires transformers and torch. "
                "Install with: pip install transformers torch"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load local model: {e}")

    def _generate_local(self, prompt: str, max_tokens: int = 500) -> str:
        """Generate text using local model."""
        import torch
        self._init_local_model()

        messages = [
            {"role": "system", "content": self.REPHRASE_SYSTEM},
            {"role": "user", "content": prompt}
        ]

        inputs = self._local_tokenizer.apply_chat_template(
            messages,
            return_tensors="pt",
            add_generation_prompt=True
        )

        # Create attention mask (1 for all tokens since there's no padding)
        attention_mask = torch.ones_like(inputs)

        # Move inputs to the same device as the model
        if hasattr(self, '_device') and self._device:
            inputs = inputs.to(self._device)
            attention_mask = attention_mask.to(self._device)
        elif hasattr(self._local_model, 'device'):
            inputs = inputs.to(self._local_model.device)
            attention_mask = attention_mask.to(self._local_model.device)

        outputs = self._local_model.generate(
            inputs,
            attention_mask=attention_mask,
            max_new_tokens=max_tokens,
            temperature=0.7,
            do_sample=True,
            pad_token_id=self._local_tokenizer.eos_token_id,
            use_cache=False  # Disable KV cache to avoid DynamicCache compatibility issues
        )

        response = self._local_tokenizer.decode(
            outputs[0][inputs.shape[1]:],
            skip_special_tokens=True
        )

        return response

    def _build_style_tone_instruction(self, style: RephraseStyle, tone: RephraseTone) -> str:
        """Build a combined instruction for style and tone."""
        style_desc = self.STYLE_PROMPTS.get(style, "")
        tone_desc = self.TONE_PROMPTS.get(tone, "")

        if tone_desc and style_desc:
            return f"{style_desc} with a {tone_desc} tone"
        elif tone_desc:
            return f"with a {tone_desc} tone"
        elif style_desc:
            return style_desc
        return "rephrased"

    def _rephrase_with_python_libs(
        self,
        text: str,
        styles: List[RephraseStyle],
        tone: RephraseTone
    ) -> List[RephraseOption]:
        """Rephrase text using Python libraries (spaCy, nltk, nlpaug) instead of AI.

        This provides rephrasing without requiring any AI/LLM.
        Uses spaCy for intelligent POS-based transformations when available,
        falling back to basic NLTK methods otherwise.
        """
        options = []
        tone_value = tone.value if tone else "neutral"

        # Check if spaCy is available for enhanced rephrasing
        spacy_available = self._init_spacy()
        method_suffix = " (spaCy)" if spacy_available else " (basic)"

        for style in styles:
            try:
                if style == RephraseStyle.CONCISE:
                    if spacy_available:
                        rephrased = self._spacy_concise(text)
                        explanation = "Used dependency parsing to remove redundant elements"
                    else:
                        rephrased = self._make_concise(text)
                        explanation = "Removed filler words and redundant phrases"

                elif style == RephraseStyle.ELABORATE:
                    if spacy_available:
                        rephrased = self._spacy_elaborate(text)
                        explanation = "Added context-aware modifiers based on sentence structure"
                    else:
                        rephrased = self._make_elaborate(text)
                        explanation = "Added descriptive modifiers and expanded phrases"

                elif style == RephraseStyle.FORMAL:
                    rephrased = self._make_formal(text)
                    explanation = "Replaced casual words with formal equivalents"

                elif style == RephraseStyle.CASUAL:
                    rephrased = self._make_casual(text)
                    explanation = "Replaced formal words with casual equivalents"

                elif style == RephraseStyle.POETIC:
                    rephrased = self._make_poetic(text)
                    explanation = "Added literary flourishes and varied word choice"

                elif style == RephraseStyle.ACTIVE_VOICE:
                    if spacy_available:
                        rephrased = self._spacy_active_voice(text)
                        explanation = "Used dependency parsing to convert passive constructions"
                    else:
                        rephrased = self._try_active_voice(text)
                        explanation = "Restructured for more active constructions"

                elif style == RephraseStyle.CLEARER:
                    if spacy_available:
                        # Use spaCy synonym replacement for clearer (POS-aware)
                        rephrased = self._make_clearer(text)
                        # Also apply POS-aware simplification
                        rephrased = self._spacy_synonym_replace(rephrased, max_replacements=2)
                        explanation = "Simplified vocabulary with POS-aware word selection"
                    else:
                        rephrased = self._make_clearer(text)
                        explanation = "Simplified vocabulary and sentence structure"

                else:
                    if spacy_available:
                        rephrased = self._spacy_synonym_replace(text, max_replacements=3)
                        explanation = "Applied POS-aware synonym substitution"
                    else:
                        rephrased = self._synonym_replace(text, max_replacements=3)
                        explanation = "Applied synonym substitution"

                options.append(RephraseOption(
                    text=rephrased,
                    style=style.value,
                    tone=tone_value,
                    explanation=explanation + method_suffix
                ))
            except Exception as e:
                options.append(RephraseOption(
                    text=text,
                    style=style.value,
                    tone=tone_value,
                    explanation=f"Could not transform: {str(e)[:50]}"
                ))

        return options

    def _get_wordnet(self):
        """Get WordNet corpus from global cache."""
        return _nlp_cache.get_wordnet()

    def _get_synonyms(self, word: str, pos=None) -> List[str]:
        """Get synonyms for a word, optionally filtered by part of speech."""
        wordnet = self._get_wordnet()
        if not wordnet:
            return []

        synonyms = set()
        synsets = wordnet.synsets(word, pos=pos) if pos else wordnet.synsets(word)

        for syn in synsets[:3]:  # Limit to first 3 synsets for relevance
            for lemma in syn.lemmas():
                name = lemma.name().replace('_', ' ')
                if name.lower() != word.lower() and len(name) < 20:
                    synonyms.add(name)
        return list(synonyms)[:5]

    def _init_spacy(self) -> bool:
        """Initialize spaCy for POS tagging and dependency parsing.

        Uses global cache for performance - spaCy model is only loaded once.

        Returns:
            True if spaCy is available and initialized, False otherwise.
        """
        # Use global cache
        self._spacy_nlp = _nlp_cache.get_spacy()
        self._spacy_available = self._spacy_nlp is not None
        return self._spacy_available

    def _spacy_pos_to_wordnet(self, spacy_pos: str):
        """Convert spaCy POS tag to WordNet POS tag.

        Args:
            spacy_pos: spaCy part-of-speech tag (e.g., 'NOUN', 'VERB', 'ADJ', 'ADV')

        Returns:
            WordNet POS constant or None if no mapping exists.
        """
        wordnet = self._get_wordnet()
        if not wordnet:
            return None

        pos_map = {
            'NOUN': wordnet.NOUN,
            'VERB': wordnet.VERB,
            'ADJ': wordnet.ADJ,
            'ADV': wordnet.ADV,
        }
        return pos_map.get(spacy_pos)

    def _get_synonyms_for_token(self, token, max_synonyms: int = 5) -> List[str]:
        """Get contextually appropriate synonyms for a spaCy token.

        Uses the token's POS tag to filter synonyms to the same part of speech.

        Args:
            token: spaCy Token object
            max_synonyms: Maximum number of synonyms to return

        Returns:
            List of synonym strings appropriate for the token's POS
        """
        wordnet = self._get_wordnet()
        if not wordnet:
            return []

        word = token.lemma_.lower()
        pos = self._spacy_pos_to_wordnet(token.pos_)

        synonyms = set()
        synsets = wordnet.synsets(word, pos=pos) if pos else wordnet.synsets(word)

        for syn in synsets[:3]:
            for lemma in syn.lemmas():
                name = lemma.name().replace('_', ' ')
                # Skip if same as original or too long
                if name.lower() != word and len(name) < 20:
                    # For verbs, try to match the original tense
                    if token.pos_ == 'VERB' and token.text != token.lemma_:
                        # Use spaCy's morphology to get the right form
                        name = self._inflect_verb(name, token)
                    synonyms.add(name)

        return list(synonyms)[:max_synonyms]

    def _inflect_verb(self, base_verb: str, original_token) -> str:
        """Attempt to inflect a verb to match the original token's form.

        Args:
            base_verb: Base form of the verb
            original_token: Original spaCy token to match

        Returns:
            Inflected verb form (best effort)
        """
        # Simple inflection rules based on morphological features
        morph = original_token.morph
        tense = morph.get("Tense", [])
        person = morph.get("Person", [])
        number = morph.get("Number", [])

        # Past tense
        if "Past" in tense:
            if base_verb.endswith('e'):
                return base_verb + 'd'
            elif base_verb.endswith('y') and len(base_verb) > 1 and base_verb[-2] not in 'aeiou':
                return base_verb[:-1] + 'ied'
            else:
                return base_verb + 'ed'

        # Present tense, third person singular
        if "Pres" in tense and "3" in person and "Sing" in number:
            if base_verb.endswith(('s', 'sh', 'ch', 'x', 'z')):
                return base_verb + 'es'
            elif base_verb.endswith('y') and len(base_verb) > 1 and base_verb[-2] not in 'aeiou':
                return base_verb[:-1] + 'ies'
            else:
                return base_verb + 's'

        # Progressive (-ing)
        if original_token.tag_ == 'VBG':
            if base_verb.endswith('ie'):
                return base_verb[:-2] + 'ying'
            elif base_verb.endswith('e') and not base_verb.endswith('ee'):
                return base_verb[:-1] + 'ing'
            else:
                return base_verb + 'ing'

        return base_verb

    def _spacy_synonym_replace(self, text: str, max_replacements: int = 3) -> str:
        """Replace words with POS-appropriate synonyms using spaCy.

        This method uses spaCy's POS tagging to ensure synonyms match the
        grammatical role of the original word.

        Args:
            text: Input text
            max_replacements: Maximum number of words to replace

        Returns:
            Text with POS-appropriate synonym replacements
        """
        if not self._init_spacy():
            # Fall back to basic synonym replacement
            return self._synonym_replace(text, max_replacements)

        doc = self._spacy_nlp(text)
        result = []
        replacements = 0

        for token in doc:
            # Only replace content words (nouns, verbs, adjectives, adverbs)
            if (replacements < max_replacements and
                token.pos_ in ('NOUN', 'VERB', 'ADJ', 'ADV') and
                len(token.text) > 3 and
                token.is_alpha and
                not token.is_stop):

                synonyms = self._get_synonyms_for_token(token)
                if synonyms:
                    replacement = synonyms[0]
                    # Preserve capitalization
                    if token.text[0].isupper():
                        replacement = replacement.capitalize()
                    if token.text.isupper():
                        replacement = replacement.upper()
                    result.append(replacement + token.whitespace_)
                    replacements += 1
                    continue

            result.append(token.text_with_ws)

        return ''.join(result)

    def _spacy_active_voice(self, text: str) -> str:
        """Convert passive voice to active voice using spaCy dependency parsing.

        Uses dependency parsing to identify passive constructions and attempt
        to restructure them into active voice.

        Args:
            text: Input text

        Returns:
            Text with passive constructions converted to active (where possible)
        """
        if not self._init_spacy():
            return self._try_active_voice(text)

        doc = self._spacy_nlp(text)
        sentences = list(doc.sents)
        result_sentences = []

        for sent in sentences:
            # Look for passive voice markers: nsubjpass (passive subject)
            passive_subj = None
            agent = None
            verb = None

            for token in sent:
                if token.dep_ == 'nsubjpass':
                    passive_subj = token
                    verb = token.head
                elif token.dep_ == 'agent':
                    # "by" phrase in passive construction
                    for child in token.children:
                        if child.dep_ == 'pobj':
                            agent = child

            # If we found a passive construction with an agent, try to convert
            if passive_subj and agent and verb:
                # Build active voice sentence
                # Agent becomes subject, passive subject becomes object
                active_parts = []

                # Get the agent phrase (may include modifiers)
                agent_phrase = self._get_phrase(agent)

                # Get the passive subject phrase
                obj_phrase = self._get_phrase(passive_subj)

                # Get the verb in active form (remove auxiliary be)
                verb_phrase = self._get_active_verb(verb)

                if agent_phrase and verb_phrase:
                    # Construct: Agent + Verb + Object + rest
                    active_parts.append(agent_phrase.capitalize())
                    active_parts.append(verb_phrase)
                    active_parts.append(obj_phrase.lower())

                    # Add any remaining parts (time expressions, etc.)
                    remaining = self._get_remaining_parts(sent, passive_subj, agent, verb)
                    if remaining:
                        active_parts.append(remaining)

                    result_sentences.append(' '.join(active_parts).strip() + '.')
                    continue

            # No passive construction found, keep original
            result_sentences.append(sent.text)

        return ' '.join(result_sentences)

    def _get_phrase(self, token) -> str:
        """Get the full phrase for a token including its modifiers.

        Args:
            token: spaCy Token

        Returns:
            Full phrase string including dependents
        """
        if token is None:
            return ""

        # Get the subtree (all descendants) sorted by position
        subtree = sorted(token.subtree, key=lambda t: t.i)
        return ' '.join(t.text for t in subtree)

    def _get_active_verb(self, passive_verb) -> str:
        """Convert a passive verb phrase to active form.

        Args:
            passive_verb: The main verb token from passive construction

        Returns:
            Active form of the verb
        """
        # For passive, we typically have "was/were/is/are + past participle"
        # We want just the active verb form

        # Get the lemma and try to match tense from auxiliary
        verb_lemma = passive_verb.lemma_
        aux_verb = None

        for child in passive_verb.children:
            if child.dep_ == 'auxpass':
                aux_verb = child
                break

        if aux_verb:
            # Match tense of auxiliary
            if aux_verb.text.lower() in ('was', 'were'):
                # Past tense
                return self._inflect_verb(verb_lemma, passive_verb)
            elif aux_verb.text.lower() in ('is', 'are', 'am'):
                # Present tense - use 3rd person singular if needed
                return verb_lemma + 's'  # Simplified

        return verb_lemma

    def _get_remaining_parts(self, sent, passive_subj, agent, verb) -> str:
        """Get remaining sentence parts not part of main passive construction.

        Args:
            sent: spaCy Span (sentence)
            passive_subj: Passive subject token
            agent: Agent token
            verb: Main verb token

        Returns:
            String of remaining parts
        """
        # Tokens to exclude (already used in reconstruction)
        exclude_indices = set()

        # Add passive subject and its subtree
        for t in passive_subj.subtree:
            exclude_indices.add(t.i)

        # Add agent and its subtree (including "by")
        if agent:
            for t in agent.subtree:
                exclude_indices.add(t.i)
            # Also exclude the "by" preposition
            if agent.head and agent.head.text.lower() == 'by':
                exclude_indices.add(agent.head.i)

        # Add verb auxiliaries
        for child in verb.children:
            if child.dep_ in ('auxpass', 'aux'):
                exclude_indices.add(child.i)

        # Collect remaining tokens
        remaining = []
        for token in sent:
            if token.i not in exclude_indices and token.i != verb.i:
                remaining.append(token.text_with_ws)

        return ''.join(remaining).strip()

    def _spacy_elaborate(self, text: str) -> str:
        """Elaborate text using spaCy to intelligently add modifiers.

        Uses dependency parsing to find appropriate places for adjectives
        and adverbs based on sentence structure.

        Args:
            text: Input text

        Returns:
            Elaborated text with contextually appropriate modifiers
        """
        if not self._init_spacy():
            return self._make_elaborate(text)

        doc = self._spacy_nlp(text)
        result = []
        modifications = 0

        # Adjectives for different noun types (based on named entity or common patterns)
        noun_adjectives = {
            'person': ['distinguished', 'remarkable', 'notable'],
            'place': ['sprawling', 'picturesque', 'vibrant'],
            'time': ['fleeting', 'memorable', 'eventful'],
            'default': ['notable', 'significant', 'remarkable']
        }

        # Adverbs for different verb types
        verb_adverbs = {
            'motion': ['swiftly', 'gracefully', 'deliberately'],
            'speech': ['softly', 'earnestly', 'thoughtfully'],
            'perception': ['intently', 'carefully', 'keenly'],
            'default': ['notably', 'significantly', 'carefully']
        }

        motion_verbs = {'walk', 'run', 'move', 'go', 'come', 'leave', 'enter', 'turn'}
        speech_verbs = {'say', 'speak', 'tell', 'ask', 'reply', 'whisper', 'shout'}
        perception_verbs = {'see', 'look', 'watch', 'hear', 'listen', 'feel', 'notice'}

        for token in doc:
            # Add adjective before nouns (if they don't already have one)
            if (token.pos_ == 'NOUN' and
                modifications < 3 and
                not any(child.pos_ == 'ADJ' for child in token.children)):

                # Determine noun category
                if token.ent_type_ in ('PERSON', 'ORG'):
                    adj_list = noun_adjectives['person']
                elif token.ent_type_ in ('GPE', 'LOC'):
                    adj_list = noun_adjectives['place']
                elif token.ent_type_ in ('DATE', 'TIME'):
                    adj_list = noun_adjectives['time']
                else:
                    adj_list = noun_adjectives['default']

                # Pick adjective based on position for variety
                adj = adj_list[modifications % len(adj_list)]
                result.append(adj + ' ')
                modifications += 1

            # Add adverb to verbs (if they don't already have one)
            elif (token.pos_ == 'VERB' and
                  token.dep_ == 'ROOT' and
                  modifications < 3 and
                  not any(child.pos_ == 'ADV' for child in token.children)):

                lemma = token.lemma_.lower()
                if lemma in motion_verbs:
                    adv_list = verb_adverbs['motion']
                elif lemma in speech_verbs:
                    adv_list = verb_adverbs['speech']
                elif lemma in perception_verbs:
                    adv_list = verb_adverbs['perception']
                else:
                    adv_list = verb_adverbs['default']

                adv = adv_list[modifications % len(adv_list)]
                result.append(token.text_with_ws)
                result.append(adv + ' ')
                modifications += 1
                continue

            result.append(token.text_with_ws)

        return ''.join(result)

    def _spacy_concise(self, text: str) -> str:
        """Make text more concise using spaCy to identify removable elements.

        Uses dependency parsing to identify redundant modifiers and phrases
        that can be removed while preserving meaning.

        Args:
            text: Input text

        Returns:
            More concise version of the text
        """
        if not self._init_spacy():
            return self._make_concise(text)

        doc = self._spacy_nlp(text)
        result = []

        # Filler adverbs that can often be removed
        filler_adverbs = {
            'very', 'really', 'quite', 'rather', 'somewhat', 'actually',
            'basically', 'literally', 'simply', 'definitely', 'certainly',
            'probably', 'possibly', 'perhaps', 'maybe', 'extremely',
            'incredibly', 'absolutely', 'totally', 'completely', 'just'
        }

        # Redundant adjectives (too vague to add meaning)
        vague_adjectives = {
            'good', 'nice', 'great', 'bad', 'big', 'small', 'certain',
            'particular', 'various', 'different', 'specific'
        }

        for token in doc:
            # Skip filler adverbs
            if token.pos_ == 'ADV' and token.text.lower() in filler_adverbs:
                # Keep if it's essential to meaning (modifying adjective in comparison)
                if token.head.pos_ == 'ADJ' and any(
                    child.dep_ == 'prep' and child.text.lower() == 'than'
                    for child in token.head.children
                ):
                    result.append(token.text_with_ws)
                else:
                    # Skip but preserve whitespace on next token
                    continue

            # Skip vague adjectives when noun is clear from context
            elif (token.pos_ == 'ADJ' and
                  token.text.lower() in vague_adjectives and
                  token.head.pos_ == 'NOUN'):
                # Skip this adjective
                continue

            # Remove "that" when it's a relative pronoun that can be omitted
            elif (token.text.lower() == 'that' and
                  token.dep_ == 'mark' and
                  token.head.pos_ == 'VERB'):
                continue

            else:
                result.append(token.text_with_ws)

        return ''.join(result).strip()

    def _synonym_replace(self, text: str, max_replacements: int = 3) -> str:
        """Replace words with synonyms while preserving meaning."""
        wordnet = self._get_wordnet()
        if not wordnet:
            return text

        words = text.split()
        replacements = 0
        result = []

        for word in words:
            clean = word.strip('.,!?;:\'"()[]')
            if len(clean) > 4 and replacements < max_replacements and clean.isalpha():
                syns = self._get_synonyms(clean.lower())
                if syns:
                    replacement = syns[0]
                    if clean[0].isupper():
                        replacement = replacement.capitalize()
                    # Preserve punctuation
                    if word != clean:
                        for c in word:
                            if not c.isalpha():
                                if word.index(c) == 0:
                                    replacement = c + replacement
                                else:
                                    replacement = replacement + c
                    result.append(replacement)
                    replacements += 1
                    continue
            result.append(word)

        return ' '.join(result)

    def _make_concise(self, text: str) -> str:
        """Make text more concise by removing filler words and redundant phrases."""
        # Filler words to remove
        filler_words = {
            'very', 'really', 'just', 'quite', 'rather', 'somewhat',
            'actually', 'basically', 'literally', 'simply', 'definitely',
            'certainly', 'probably', 'possibly', 'perhaps', 'maybe',
            'extremely', 'incredibly', 'absolutely', 'totally', 'completely'
        }

        # Redundant phrase replacements
        redundant_phrases = {
            'in order to': 'to',
            'due to the fact that': 'because',
            'at this point in time': 'now',
            'in the event that': 'if',
            'for the purpose of': 'to',
            'with regard to': 'about',
            'in spite of the fact that': 'although',
            'as a matter of fact': '',
            'the fact that': 'that',
            'it is important to note that': '',
            'it should be noted that': '',
            'needless to say': '',
            'at the present time': 'now',
            'in the near future': 'soon',
            'a large number of': 'many',
            'a small number of': 'few',
            'the vast majority of': 'most',
        }

        result = text
        # Replace redundant phrases
        for phrase, replacement in redundant_phrases.items():
            result = result.replace(phrase, replacement)
            result = result.replace(phrase.capitalize(), replacement.capitalize() if replacement else '')

        # Remove filler words
        words = result.split()
        filtered = []
        for i, word in enumerate(words):
            word_lower = word.lower().strip('.,!?;:')
            if word_lower not in filler_words:
                filtered.append(word)
            elif i > 0 and words[i-1].lower() in {'is', 'was', 'are', 'were', 'be', 'been'}:
                filtered.append(word)  # Keep after be-verbs

        return ' '.join(filtered)

    def _make_elaborate(self, text: str) -> str:
        """Make text more elaborate by adding modifiers and expanding phrases."""
        # Adjective additions for common nouns
        noun_modifiers = {
            'man': 'distinguished man',
            'woman': 'graceful woman',
            'house': 'charming house',
            'room': 'spacious room',
            'day': 'eventful day',
            'night': 'quiet night',
            'sun': 'brilliant sun',
            'sky': 'expansive sky',
            'door': 'heavy wooden door',
            'window': 'large window',
            'tree': 'tall tree',
            'road': 'winding road',
            'car': 'sleek car',
            'voice': 'resonant voice',
            'eyes': 'expressive eyes',
            'face': 'weathered face',
            'hand': 'steady hand',
            'heart': 'beating heart',
        }

        # Adverb additions for common verbs
        verb_modifiers = {
            'walked': 'walked deliberately',
            'ran': 'ran swiftly',
            'said': 'said thoughtfully',
            'looked': 'looked intently',
            'stood': 'stood firmly',
            'sat': 'sat quietly',
            'moved': 'moved gracefully',
            'turned': 'turned slowly',
            'smiled': 'smiled warmly',
            'spoke': 'spoke clearly',
        }

        words = text.split()
        result = []
        modified = 0

        for i, word in enumerate(words):
            clean = word.lower().strip('.,!?;:\'"')

            if modified < 3:  # Limit modifications
                if clean in noun_modifiers:
                    replacement = noun_modifiers[clean]
                    if word[0].isupper():
                        replacement = replacement.capitalize()
                    # Preserve punctuation
                    suffix = ''.join(c for c in word if not c.isalpha())
                    result.append(replacement + suffix)
                    modified += 1
                    continue
                elif clean in verb_modifiers:
                    replacement = verb_modifiers[clean]
                    suffix = ''.join(c for c in word if not c.isalpha())
                    result.append(replacement + suffix)
                    modified += 1
                    continue

            result.append(word)

        return ' '.join(result)

    def _make_formal(self, text: str) -> str:
        """Make text more formal by replacing casual words."""
        # Casual to formal replacements
        formal_replacements = {
            "can't": "cannot",
            "won't": "will not",
            "don't": "do not",
            "doesn't": "does not",
            "isn't": "is not",
            "aren't": "are not",
            "wasn't": "was not",
            "weren't": "were not",
            "haven't": "have not",
            "hasn't": "has not",
            "wouldn't": "would not",
            "couldn't": "could not",
            "shouldn't": "should not",
            "didn't": "did not",
            "i'm": "I am",
            "you're": "you are",
            "we're": "we are",
            "they're": "they are",
            "it's": "it is",
            "that's": "that is",
            "let's": "let us",
            "gonna": "going to",
            "wanna": "want to",
            "gotta": "have to",
            "kinda": "kind of",
            "sorta": "sort of",
            "ok": "acceptable",
            "okay": "acceptable",
            "yeah": "yes",
            "yep": "yes",
            "nope": "no",
            "hi": "hello",
            "hey": "hello",
            "bye": "goodbye",
            "kids": "children",
            "guys": "individuals",
            "stuff": "materials",
            "things": "matters",
            "a lot": "considerably",
            "lots of": "numerous",
            "big": "substantial",
            "small": "minimal",
            "good": "satisfactory",
            "bad": "unsatisfactory",
            "nice": "pleasant",
            "great": "excellent",
            "pretty": "rather",
            "get": "obtain",
            "got": "obtained",
            "buy": "purchase",
            "bought": "purchased",
            "use": "utilize",
            "show": "demonstrate",
            "find": "locate",
            "help": "assist",
            "need": "require",
            "want": "desire",
            "like": "prefer",
            "think": "believe",
            "try": "attempt",
            "start": "commence",
            "end": "conclude",
            "begin": "initiate",
        }

        result = text
        for casual, formal in formal_replacements.items():
            # Case-insensitive replacement while preserving case
            pattern = re.compile(re.escape(casual), re.IGNORECASE)

            def make_replacer(formal_word):
                def replace_match(match):
                    orig = match.group(0)
                    if orig.isupper():
                        return formal_word.upper()
                    elif orig[0].isupper():
                        return formal_word.capitalize()
                    return formal_word
                return replace_match

            result = pattern.sub(make_replacer(formal), result)

        return result

    def _make_casual(self, text: str) -> str:
        """Make text more casual by using contractions and informal words."""
        # Formal to casual replacements
        casual_replacements = {
            "cannot": "can't",
            "will not": "won't",
            "do not": "don't",
            "does not": "doesn't",
            "is not": "isn't",
            "are not": "aren't",
            "was not": "wasn't",
            "were not": "weren't",
            "have not": "haven't",
            "has not": "hasn't",
            "would not": "wouldn't",
            "could not": "couldn't",
            "should not": "shouldn't",
            "did not": "didn't",
            "I am": "I'm",
            "you are": "you're",
            "we are": "we're",
            "they are": "they're",
            "it is": "it's",
            "that is": "that's",
            "let us": "let's",
            "going to": "gonna",
            "want to": "wanna",
            "purchase": "buy",
            "utilize": "use",
            "demonstrate": "show",
            "locate": "find",
            "assist": "help",
            "require": "need",
            "desire": "want",
            "prefer": "like",
            "believe": "think",
            "attempt": "try",
            "commence": "start",
            "conclude": "end",
            "initiate": "begin",
            "obtain": "get",
            "considerable": "a lot",
            "numerous": "lots of",
            "substantial": "big",
            "minimal": "small",
            "satisfactory": "good",
            "unsatisfactory": "bad",
            "pleasant": "nice",
            "excellent": "great",
            "children": "kids",
            "individuals": "people",
        }

        result = text
        for formal, casual in casual_replacements.items():
            pattern = re.compile(re.escape(formal), re.IGNORECASE)

            def make_replacer(casual_word):
                def replace_match(match):
                    orig = match.group(0)
                    if orig.isupper():
                        return casual_word.upper()
                    elif orig[0].isupper():
                        return casual_word.capitalize()
                    return casual_word
                return replace_match

            result = pattern.sub(make_replacer(casual), result)

        return result

    def _make_poetic(self, text: str) -> str:
        """Make text more poetic with literary word choices and structure."""
        # Poetic word substitutions
        poetic_replacements = {
            'sky': 'heavens',
            'sun': 'golden orb',
            'moon': 'silver moon',
            'night': 'eventide',
            'morning': 'dawn',
            'evening': 'dusk',
            'sea': 'briny deep',
            'ocean': 'vast waters',
            'wind': 'zephyr',
            'rain': 'gentle rain',
            'eyes': 'orbs',
            'heart': 'beating heart',
            'soul': 'eternal soul',
            'love': 'ardent love',
            'death': 'final rest',
            'life': 'mortal coil',
            'time': 'fleeting time',
            'dream': 'reverie',
            'sleep': 'slumber',
            'tears': 'crystal tears',
            'smile': 'gentle smile',
            'voice': 'melodious voice',
            'silence': 'hushed silence',
            'dark': 'shadowed',
            'light': 'radiant light',
            'cold': 'bitter cold',
            'warm': 'gentle warmth',
            'beautiful': 'wondrous',
            'sad': 'melancholy',
            'happy': 'joyous',
            'old': 'ancient',
            'young': 'youthful',
            'walked': 'wandered',
            'ran': 'fled',
            'said': 'whispered',
            'cried': 'wept',
            'looked': 'gazed',
        }

        words = text.split()
        result = []
        modified = 0

        for word in words:
            clean = word.lower().strip('.,!?;:\'"')
            if clean in poetic_replacements and modified < 4:
                replacement = poetic_replacements[clean]
                if word[0].isupper():
                    replacement = replacement.capitalize()
                suffix = ''.join(c for c in word if not c.isalpha())
                result.append(replacement + suffix)
                modified += 1
            else:
                result.append(word)

        return ' '.join(result)

    def _make_clearer(self, text: str) -> str:
        """Make text clearer by simplifying vocabulary and structure."""
        # Complex to simple word replacements
        simple_replacements = {
            'utilize': 'use',
            'implement': 'do',
            'facilitate': 'help',
            'leverage': 'use',
            'optimize': 'improve',
            'endeavor': 'try',
            'subsequently': 'then',
            'consequently': 'so',
            'nevertheless': 'but',
            'notwithstanding': 'despite',
            'aforementioned': 'this',
            'commence': 'start',
            'terminate': 'end',
            'ascertain': 'find out',
            'comprehend': 'understand',
            'demonstrate': 'show',
            'sufficient': 'enough',
            'approximately': 'about',
            'numerous': 'many',
            'additional': 'more',
            'regarding': 'about',
            'concerning': 'about',
            'prior to': 'before',
            'subsequent to': 'after',
            'in lieu of': 'instead of',
            'in conjunction with': 'with',
            'in accordance with': 'following',
            'with respect to': 'about',
            'pertaining to': 'about',
            'in the absence of': 'without',
        }

        result = text
        for complex_word, simple_word in simple_replacements.items():
            pattern = re.compile(re.escape(complex_word), re.IGNORECASE)

            def make_replacer(simple):
                def replace_match(match):
                    orig = match.group(0)
                    if orig.isupper():
                        return simple.upper()
                    elif orig[0].isupper():
                        return simple.capitalize()
                    return simple
                return replace_match

            result = pattern.sub(make_replacer(simple_word), result)

        return result

    def _try_active_voice(self, text: str) -> str:
        """Attempt to convert passive voice to active voice."""
        try:
            import nltk
            from nltk import pos_tag, word_tokenize

            # Ensure NLTK data is available (uses global cache)
            _nlp_cache.ensure_nltk_ready()

            # Simple passive voice indicators
            passive_indicators = ['was', 'were', 'is', 'are', 'been', 'being', 'be']
            words = word_tokenize(text)
            tagged = pos_tag(words)

            # Look for passive patterns (be + past participle)
            result = []
            i = 0
            while i < len(tagged):
                word, tag = tagged[i]
                if word.lower() in passive_indicators and i + 1 < len(tagged):
                    next_word, next_tag = tagged[i + 1]
                    if next_tag == 'VBN':  # Past participle
                        # Mark as identified passive but keep as-is
                        # (true conversion would require understanding subject/object)
                        result.append(word)
                        result.append(next_word)
                        i += 2
                        continue
                result.append(word)
                i += 1

            # Join with proper spacing (handle punctuation)
            final = []
            for i, word in enumerate(result):
                if word in '.,!?;:\'"' or (i > 0 and result[i-1] in '(\'"'):
                    if final:
                        final[-1] = final[-1] + word
                    else:
                        final.append(word)
                else:
                    final.append(word)

            return ' '.join(final)

        except Exception:
            return text

    def _rephrase_with_nltk_only(
        self,
        text: str,
        styles: List[RephraseStyle],
        tone_value: str
    ) -> List[RephraseOption]:
        """Fallback rephrasing using only NLTK when nlpaug is not available."""
        options = []

        # Get WordNet from cache
        wordnet = _nlp_cache.get_wordnet()
        if wordnet is None:
            # Even NLTK not available - return original with message
            for style in styles:
                options.append(RephraseOption(
                    text=text,
                    style=style.value,
                    tone=tone_value,
                    explanation="Install nltk for basic rephrasing: pip install nltk"
                ))
            return options

        try:
            def get_synonyms(word):
                """Get synonyms for a word from WordNet."""
                synonyms = set()
                for syn in wordnet.synsets(word):
                    for lemma in syn.lemmas():
                        if lemma.name() != word and '_' not in lemma.name():
                            synonyms.add(lemma.name())
                return list(synonyms)

            words = text.split()

            for style in styles:
                if style == RephraseStyle.CONCISE:
                    rephrased = self._make_concise(text)
                    explanation = "Removed filler words"
                elif style == RephraseStyle.ACTIVE_VOICE:
                    rephrased = self._try_active_voice(text)
                    explanation = "Attempted active voice conversion"
                else:
                    # Replace some words with synonyms
                    new_words = []
                    changes = 0
                    for word in words:
                        clean_word = word.strip('.,!?;:\'"')
                        if len(clean_word) > 4 and changes < 3:  # Only replace longer words
                            syns = get_synonyms(clean_word.lower())
                            if syns:
                                # Preserve capitalization and punctuation
                                replacement = syns[0]
                                if clean_word[0].isupper():
                                    replacement = replacement.capitalize()
                                # Restore punctuation
                                if word != clean_word:
                                    for char in word:
                                        if char in '.,!?;:\'"':
                                            if word.startswith(char):
                                                replacement = char + replacement
                                            else:
                                                replacement = replacement + char
                                new_words.append(replacement)
                                changes += 1
                                continue
                        new_words.append(word)

                    rephrased = ' '.join(new_words)
                    explanation = f"Replaced {changes} words with synonyms"

                options.append(RephraseOption(
                    text=rephrased,
                    style=style.value,
                    tone=tone_value,
                    explanation=explanation
                ))

        except Exception:
            # Error during processing - return original with message
            for style in styles:
                if not any(opt.style == style.value for opt in options):
                    options.append(RephraseOption(
                        text=text,
                        style=style.value,
                        tone=tone_value,
                        explanation="Processing error - original text preserved"
                    ))

        return options

    def rephrase(
        self,
        text: str,
        styles: Optional[List[RephraseStyle]] = None,
        tone: RephraseTone = RephraseTone.NEUTRAL,
        context: str = "",
        num_options: int = 4
    ) -> RephraseResult:
        """Generate multiple rephrasing options for text.

        Args:
            text: Text to rephrase
            styles: Optional list of specific styles to generate
            tone: Tone to apply to all variations (default: neutral)
            context: Optional context about the text (character, scene, etc.)
            num_options: Number of options to generate if no styles specified

        Returns:
            RephraseResult with multiple options
        """
        if not styles:
            # Default styles for variety
            styles = [
                RephraseStyle.CONCISE,
                RephraseStyle.CLEARER,
                RephraseStyle.ELABORATE,
                RephraseStyle.FORMAL
            ][:num_options]

        # Build prompt
        context_str = f"\nContext: {context}\n" if context else ""

        # Build instructions combining style and tone
        style_instructions = "\n".join([
            f"{i+1}. {self._build_style_tone_instruction(style, tone)} ({style.value})"
            for i, style in enumerate(styles)
        ])

        # Add tone description to prompt if not neutral
        tone_note = ""
        if tone != RephraseTone.NEUTRAL:
            tone_note = f"\nApply a {self.TONE_PROMPTS[tone]} tone to all variations.\n"

        # Build format example based on number of styles
        format_examples = []
        for i, style in enumerate(styles[:2]):  # Show at most 2 examples
            format_examples.append(f"""OPTION {i+1} ({style.value}):
[rephrased text]
EXPLANATION: [brief explanation]""")

        format_example_str = "\n\n".join(format_examples)
        if len(styles) > 2:
            format_example_str += "\n\n(continue for all options)"

        prompt = f"""Please rephrase the following text in {len(styles)} different ways:

Original text: "{text}"
{context_str}{tone_note}
Generate these variations:
{style_instructions}

For each variation, provide:
- The rephrased text
- A brief explanation (1 sentence) of what changed

Format your response as:
{format_example_str}
"""

        # Use Python libraries if AI is disabled
        if self.use_python_libraries:
            options = self._rephrase_with_python_libs(text, styles, tone)
            return RephraseResult(
                original=text,
                options=options,
                model_used="python-libraries",
                cost_estimate=0.0
            )

        # Generate using either local or cloud model
        if self.use_local_model:
            response = self._generate_local(prompt, max_tokens=800)
            model_used = "local-phi-3"
            cost = 0.0
        else:
            if not self.llm:
                raise ValueError("No LLM client configured. Enable local model or provide LLM client.")

            response = self.llm.generate_text(
                prompt,
                self.REPHRASE_SYSTEM,
                max_tokens=800,
                temperature=0.7
            )
            model_used = self.llm.model if hasattr(self.llm, 'model') else "unknown"
            cost = 0.002  # Rough estimate

        # Parse response
        options = self._parse_response(response, styles, tone)

        return RephraseResult(
            original=text,
            options=options,
            model_used=model_used,
            cost_estimate=cost
        )

    def _parse_response(self, response: str, styles: List[RephraseStyle], tone: RephraseTone = RephraseTone.NEUTRAL) -> List[RephraseOption]:
        """Parse LLM response into structured options."""
        options = []
        tone_value = tone.value if tone else "neutral"

        # Split by option markers
        lines = response.split('\n')
        current_option = None
        current_text = []
        current_explanation = ""
        current_style = None

        for line in lines:
            line = line.strip()

            # Check for option header
            if line.upper().startswith("OPTION"):
                # Save previous option if exists
                if current_option and current_text:
                    options.append(RephraseOption(
                        text=' '.join(current_text).strip(),
                        style=current_style or "general",
                        tone=tone_value,
                        explanation=current_explanation
                    ))

                # Start new option
                current_text = []
                current_explanation = ""

                # Extract style from header if present
                for style in styles:
                    if style.value.lower() in line.lower():
                        current_style = style.value
                        break
                else:
                    current_style = "general"

                current_option = True

            elif line.upper().startswith("EXPLANATION:"):
                current_explanation = line.split(":", 1)[1].strip()

            elif current_option and line and not line.startswith("["):
                # Add to current text (skip placeholder brackets)
                if not line.startswith("(") or not line.endswith(")"):
                    current_text.append(line)

        # Add last option
        if current_option and current_text:
            options.append(RephraseOption(
                text=' '.join(current_text).strip(),
                style=current_style or "general",
                tone=tone_value,
                explanation=current_explanation
            ))

        # If parsing failed, try simpler approach
        if not options:
            # Just split by double newlines and take non-empty sections
            sections = response.split('\n\n')
            for i, section in enumerate(sections):
                section = section.strip()
                if section and len(section) > 10:
                    # Clean up common markers
                    for marker in ["Option", "Variation", "Alternative", "1.", "2.", "3.", "4."]:
                        if section.startswith(marker):
                            section = section[len(marker):].strip()
                            if section.startswith(":"):
                                section = section[1:].strip()
                            break

                    style = styles[i].value if i < len(styles) else "general"
                    options.append(RephraseOption(
                        text=section,
                        style=style,
                        tone=tone_value,
                        explanation=""
                    ))

                if len(options) >= len(styles):
                    break

        return options

    def quick_rephrase(self, text: str, style: RephraseStyle, tone: RephraseTone = RephraseTone.NEUTRAL) -> str:
        """Quickly rephrase text in a single style with optional tone.

        Args:
            text: Text to rephrase
            style: Style to use
            tone: Tone to apply (default: neutral)

        Returns:
            Rephrased text
        """
        instruction = self._build_style_tone_instruction(style, tone)
        prompt = f"""Rephrase the following text to be {instruction}:

"{text}"

Provide only the rephrased text, nothing else."""

        if self.use_local_model:
            response = self._generate_local(prompt, max_tokens=300)
        else:
            if not self.llm:
                raise ValueError("No LLM client configured.")

            response = self.llm.generate_text(
                prompt,
                "You are a helpful writing assistant. Provide only the rephrased text.",
                max_tokens=300,
                temperature=0.7
            )

        # Clean up response
        response = response.strip()
        if response.startswith('"') and response.endswith('"'):
            response = response[1:-1]

        return response
