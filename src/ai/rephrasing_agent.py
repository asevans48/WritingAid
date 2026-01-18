"""Rephrasing agent for text rewriting with multiple options."""

from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.models.project import WriterProject


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
        local_model_id: Optional[str] = None
    ):
        """Initialize rephrasing agent.

        Args:
            llm_client: LLM client for API calls
            project: Project for context
            use_local_model: Whether to use local SLM instead of cloud API
            local_model_id: Optional model ID to use for local model (from settings)
        """
        self.llm = llm_client
        self.project = project
        self.use_local_model = use_local_model
        self.local_model_id = local_model_id
        self._local_model = None
        self._local_tokenizer = None
        self._device = None

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

        # Move inputs to the same device as the model
        if hasattr(self, '_device') and self._device:
            inputs = inputs.to(self._device)
        elif hasattr(self._local_model, 'device'):
            inputs = inputs.to(self._local_model.device)

        outputs = self._local_model.generate(
            inputs,
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

        prompt = f"""Please rephrase the following text in {len(styles)} different ways:

Original text: "{text}"
{context_str}{tone_note}
Generate these variations:
{style_instructions}

For each variation, provide:
- The rephrased text
- A brief explanation (1 sentence) of what changed

Format your response as:
OPTION 1 ({styles[0].value}):
[rephrased text]
EXPLANATION: [brief explanation]

OPTION 2 ({styles[1].value}):
[rephrased text]
EXPLANATION: [brief explanation]

(continue for all options)
"""

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


# Public functions for model cache management
def get_cached_model_info() -> Optional[str]:
    """Get info about the currently cached local model.

    Returns:
        Model ID if a model is cached, None otherwise.
    """
    return _model_cache.get_loaded_model_id()


def is_local_model_loaded(model_id: str = None) -> bool:
    """Check if a local model is loaded in the cache.

    Args:
        model_id: Optional specific model ID to check for.

    Returns:
        True if a model (or the specific model) is cached.
    """
    return _model_cache.is_loaded(model_id)


def unload_local_model():
    """Unload the cached local model to free memory/GPU."""
    _model_cache.unload()
