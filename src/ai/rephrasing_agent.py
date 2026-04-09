"""Rephrasing agent for text rewriting with multiple options."""

import sys
import re
import threading
import platform
import time
from typing import List, Optional, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum
from src.ai.device_utils import detect_device, print_device_info
from src.ai.mlx_utils import can_use_mlx, _mlx_cache as mlx_cache

# macOS-specific: Increase stack size (addresses C stack overflow issues)
# macOS has a default C stack size of 500KB which is too small for deep model architectures
# Windows doesn't have the resource module and doesn't need this fix
if platform.system() == "Darwin":
    try:
        import resource
        # Get current stack size limit
        soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_STACK)
        print(f"[MODULE INIT] Current stack size: {soft_limit / (1024*1024):.1f}MB (hard limit: {hard_limit / (1024*1024):.1f}MB)")

        # Try to increase to the hard limit if current is lower
        if soft_limit < hard_limit:
            resource.setrlimit(resource.RLIMIT_STACK, (hard_limit, hard_limit))
            print(f"[MODULE INIT] Stack size increased to {hard_limit / (1024*1024):.1f}MB")
        else:
            print(f"[MODULE INIT] Stack size already at maximum")

        # Also set thread stack size for any worker threads
        try:
            threading.stack_size(int(soft_limit))
        except ValueError:
            pass  # Threading stack size setting might not be supported
    except (ValueError, OSError, ImportError) as e:
        # Stack size setting might fail on some systems
        print(f"[MODULE INIT] Could not adjust stack size: {e}")

# Increase recursion limit BEFORE importing torch/transformers to prevent stack overflow
# Both PyTorch and Transformers can trigger deep recursion during import on some platforms
# This is especially critical for Gemma3 and other models with complex architecture definitions
_original_recursion_limit = sys.getrecursionlimit()
sys.setrecursionlimit(10000)

print(f"[MODULE INIT] Importing PyTorch and Transformers with recursion limit: {sys.getrecursionlimit()}")

# Import torch at module level to avoid repeated imports causing stack overflow
_TORCH_IMPORT_ERROR = None
try:
    import torch
    _TORCH_AVAILABLE = True
    print("[MODULE INIT] [OK] PyTorch imported successfully")
except ImportError as e:
    _TORCH_AVAILABLE = False
    _TORCH_IMPORT_ERROR = str(e)
    torch = None
    print(f"[MODULE INIT] [FAIL] PyTorch not available: {e}")

# Import transformers at module level with high recursion limit
# This is especially important for Gemma3 and other models with deep architecture definitions
_TRANSFORMERS_IMPORT_ERROR = None
try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    _TRANSFORMERS_AVAILABLE = True
    print("[MODULE INIT] [OK] Transformers imported successfully")
except ImportError as e:
    _TRANSFORMERS_AVAILABLE = False
    _TRANSFORMERS_IMPORT_ERROR = str(e)
    AutoModelForCausalLM = None
    AutoTokenizer = None
    print(f"[MODULE INIT] [FAIL] Transformers not available: {e}")
except Exception as e:
    # Catch any other error (like UnicodeEncodeError from print statements)
    _TRANSFORMERS_AVAILABLE = False
    _TRANSFORMERS_IMPORT_ERROR = f"Unexpected error during import: {type(e).__name__}: {e}"
    AutoModelForCausalLM = None
    AutoTokenizer = None
    print(f"[MODULE INIT] [FAIL] Transformers import failed with unexpected error: {e}")

# Import MLX for Apple Silicon optimization
try:
    if can_use_mlx():
        _MLX_AVAILABLE = True
        print("[MODULE INIT] [OK] MLX available - using Apple Silicon optimized inference")
    else:
        _MLX_AVAILABLE = False
        print("[MODULE INIT] [FAIL] MLX not available (not on Apple Silicon)")
except ImportError as e:
    _MLX_AVAILABLE = False
    print(f"[MODULE INIT] [FAIL] MLX not available: {e}")

# Restore original limit after imports
sys.setrecursionlimit(_original_recursion_limit)
print(f"[MODULE INIT] Recursion limit restored to: {sys.getrecursionlimit()}")

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

# Global flag: once CUDA assertion fails, all subsequent calls use CPU
_cuda_failed = False


class RephraseStyle(Enum):
    """Available rephrasing styles (structural/writing approach)."""
    CONCISE = "concise"
    ELABORATE = "elaborate"
    FORMAL = "formal"
    CASUAL = "casual"
    POETIC = "poetic"
    ACTIVE_VOICE = "active_voice"
    CLEARER = "clearer"
    # Extended styles
    SENSORY = "sensory"  # Add sensory details
    PUNCHY = "punchy"  # Short, impactful sentences
    FLOWING = "flowing"  # Longer, flowing prose
    SPARSE = "sparse"  # Minimalist style
    LITERARY = "literary"  # More artistic


class RephraseTone(Enum):
    """Available rephrasing tones (emotional quality)."""
    NEUTRAL = "neutral"
    DARK = "dark"
    DRAMATIC = "dramatic"
    HOPEFUL = "hopeful"
    HAPPY = "happy"
    PROUD = "proud"
    MELANCHOLIC = "melancholic"
    SORROWFUL = "sorrowful"
    NOSTALGIC = "nostalgic"
    TENSE = "tense"
    WHIMSICAL = "whimsical"
    GROSS = "gross"
    # Extended tones
    MYSTERIOUS = "mysterious"
    ROMANTIC = "romantic"
    HUMOROUS = "humorous"
    OMINOUS = "ominous"
    URGENT = "urgent"


@dataclass
class RephraseContext:
    """Context for rephrasing operations."""
    character_voice: str = ""  # Whose POV/voice
    scene_mood: str = ""  # Current scene mood
    genre: str = ""  # Genre conventions to follow
    plot_context: str = ""  # What's happening in the plot


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


# Mapping from personality traits → concrete writing style directives
_TRAIT_VOICE_MAP = {
    # Emotional traits → sentence structure and word choice
    "stoic": "Use short, declarative sentences. Avoid emotional language. Favor understatement.",
    "calm": "Use measured pacing. Avoid exclamation. Favor deliberate, unhurried phrasing.",
    "anxious": "Use fragmented thoughts, qualifiers ('maybe', 'probably'). Shorter sentences when tense.",
    "confident": "Use strong, direct statements. No hedging. Favor active voice and certainty.",
    "insecure": "Use self-correcting phrases, hesitation. Avoid bold declarations.",
    "sarcastic": "Use dry understatement, ironic contrast. Say the opposite of what's meant.",
    "warm": "Use inclusive language ('we', 'us'). Softer word choices. Longer, flowing sentences.",
    "cold": "Use clinical, detached language. Short sentences. Avoid warmth words.",
    "cheerful": "Use bright, energetic words. Shorter, punchy sentences. Exclamation marks sparingly.",
    "brooding": "Use longer, heavier sentences. Dark imagery. Introspective phrasing.",
    "playful": "Use unexpected word choices, light rhythm. Occasional humor or teasing tone.",
    "serious": "Use measured, deliberate word choice. No levity. Weighty phrasing.",
    "cynical": "Use world-weary phrasing. Expect the worst. Dismissive of idealism.",
    "optimistic": "Frame negatives as opportunities. Forward-looking language.",
    "cautious": "Use conditional language ('if', 'might', 'could'). Hedge statements.",
    "reckless": "Use impulsive, action-oriented language. Short, blunt. No hesitation.",
    "loyal": "Reference duty, promises, bonds. Firm convictions about people.",
    "selfish": "Frame everything in terms of personal gain or loss.",
    "honest": "Direct, no euphemisms. Say things plainly even when uncomfortable.",
    "deceptive": "Use careful word choice that technically doesn't lie. Misdirect.",
    "proud": "Use elevated language. Resist showing weakness. Dignified phrasing.",
    "humble": "Downplay achievements. Deflect praise. Simple, unadorned language.",
    "gentle": "Use soft consonants, flowing rhythms. Avoid harsh or blunt phrasing.",
    "fierce": "Use sharp, punchy words. Hard consonants. Aggressive rhythm.",
    "patient": "Use unhurried phrasing. Long, complete thoughts. No rushing.",
    "impatient": "Use clipped sentences. Interruptions. Cut to the point.",
    "compassionate": "Acknowledge others' feelings. Use empathetic framing.",
    "ruthless": "Use cold, calculating language. Efficiency over emotion.",
    "disciplined": "Use structured, orderly sentences. Military precision.",
    "chaotic": "Use run-on thoughts, tangents, unexpected pivots.",
    "clever": "Use wordplay, double meanings. Precise vocabulary.",
    "stubborn": "Use repetition, refusal language. 'No.' 'I won't.' Dig in.",
    "quiet": "Use fewer words. Let silence speak. Short, sparse sentences.",
    "loud": "Use emphatic language. Bold statements. Fill the space.",
}

# Mapping from speaking style keywords → writing directives
_SPEECH_STYLE_MAP = {
    "soft-spoken": "Keep volume low — whispered asides, gentle word choice.",
    "clipped": "Maximum 8-10 words per sentence in dialogue. No filler.",
    "formal": "Use proper grammar, no contractions, elevated vocabulary.",
    "casual": "Use contractions, slang, conversational rhythm.",
    "sarcastic": "Understatement, ironic contrast, deadpan delivery.",
    "direct": "Subject-verb-object. No circling around the point.",
    "verbose": "Use longer explanations, tangents, over-qualification.",
    "terse": "Minimum words. Grunts. Single-word answers.",
    "drawl": "Use stretched vowels in dialogue, unhurried rhythm.",
    "accent": "Suggest accent through word order and idiom, not spelling.",
    "humor": "Break tension with unexpected observations or dry wit.",
    "forceful": "Use imperative mood. Commands. No room for argument.",
}


def _build_character_voice_rules(character_context: str) -> str:
    """Convert character traits and profile into concrete writing directives.

    Takes the character context string (from _get_selected_characters_context)
    and maps traits, speaking style, and personality to actionable rules
    that tell the LLM exactly how to phrase things for this character.
    """
    context_lower = character_context.lower()
    rules = []

    # Match personality traits
    for trait, rule in _TRAIT_VOICE_MAP.items():
        if trait in context_lower:
            rules.append(f"• {rule}")

    # Match speaking style patterns
    for pattern, rule in _SPEECH_STYLE_MAP.items():
        if pattern in context_lower:
            rules.append(f"• {rule}")

    # Extract specific guidance from character fields
    if "motivations:" in context_lower:
        rules.append("• Filter word choices through what this character WANTS — "
                      "their motivation colors how they see everything.")
    if "fears:" in context_lower:
        rules.append("• The character's fears affect their language — "
                      "they avoid, deflect, or overcompensate around what scares them.")
    if "emotional baseline:" in context_lower:
        rules.append("• Return to the character's baseline mood between emotional peaks. "
                      "This is their 'resting voice.'")

    if not rules:
        rules.append("• Write as this character would naturally think and speak.")
        rules.append("• Match their education level, social class, and temperament.")

    return "\n".join(rules)


class RephrasingAgent:
    """Agent for generating multiple rephrasing options for text.

    Supports both cloud LLMs and local small language models (SLMs).
    """

    REPHRASE_SYSTEM = """You are a skilled editor helping an author rephrase their writing.
Your job is to provide several alternative phrasings while preserving the original meaning.

You may receive CHARACTER DETAILS, SCENE context, WORLDBUILDING reference, and THESAURUS data.
Use them in this priority order:
1. CHARACTER VOICE — if a character is specified, the rephrasing must sound like them
2. SCENE CONTEXT — match the emotional beat and action of the surrounding text
3. WORLDBUILDING — use terminology, names, and concepts from the author's world
4. REFERENCE/THESAURUS — draw from these for vocabulary options and grounding in reality

Guidelines:
- Maintain the original intent and key information
- Apply the requested style (structural approach) and tone (emotional quality)
- TONE IS CRITICAL: The emotional tone must be felt in every word choice, sentence rhythm, and image. Don't just describe the emotion — make the reader FEEL it through the prose itself. Use word connotation, sentence length, imagery, and rhythm to embody the tone.
- When multiple tones are requested, weave them together naturally — do not switch between them, blend them into a single emotional texture
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
        # Extended styles
        RephraseStyle.SENSORY: "rich with sensory details (sight, sound, smell, touch, taste)",
        RephraseStyle.PUNCHY: "short, punchy, and impactful with strong verbs",
        RephraseStyle.FLOWING: "longer, flowing prose with smooth transitions",
        RephraseStyle.SPARSE: "minimalist and sparse, only essential words",
        RephraseStyle.LITERARY: "literary and artistic with vivid imagery",
    }

    # Tone prompts — rich guidance so the LLM embodies the emotion in prose
    TONE_PROMPTS = {
        RephraseTone.NEUTRAL: "",
        RephraseTone.DARK: (
            "dark and ominous — use heavy, shadowed imagery; favor words with hard "
            "consonants and negative connotations; let dread seep through the sentence "
            "structure; shorter sentences build unease, longer ones suffocate"
        ),
        RephraseTone.DRAMATIC: (
            "dramatic and impactful — heighten every beat; use contrast and reversal; "
            "build to a punch at the end of sentences; let the weight of the moment land; "
            "employ rhetorical devices like repetition, parallelism, or antithesis"
        ),
        RephraseTone.HOPEFUL: (
            "hopeful and optimistic — use ascending imagery (light, rising, opening); "
            "favor warm vowel sounds; let sentences breathe with possibility; "
            "the prose should feel like dawn breaking or a door opening"
        ),
        RephraseTone.HAPPY: (
            "warm and joyful — use bright, lively word choices; quick rhythms and "
            "buoyant sentence structures; sensory details that feel pleasant (warmth, "
            "light, laughter); the prose should make the reader smile"
        ),
        RephraseTone.PROUD: (
            "proud and triumphant — use strong, declarative sentences; elevated diction; "
            "imagery of standing tall, light catching, weight lifted; the prose should "
            "feel like a chest swelling, a flag unfurling"
        ),
        RephraseTone.MELANCHOLIC: (
            "melancholic and wistful — use soft, fading imagery; longer sentences that "
            "trail off; words that echo loss without naming it directly; the beauty is "
            "in what's missing; muted colors, quiet sounds, empty spaces"
        ),
        RephraseTone.SORROWFUL: (
            "sorrowful and grief-stricken — use raw, physical language; short sentences "
            "that land like blows; sensory details of absence; the prose should ache; "
            "avoid sentimentality — genuine grief is sparse and stunned"
        ),
        RephraseTone.NOSTALGIC: (
            "nostalgic and reminiscent — use past-tense framing even in present action; "
            "sensory details that trigger memory (specific smells, textures, sounds); "
            "a gentle ache of distance from something once-loved; warm but tinged with loss"
        ),
        RephraseTone.TENSE: (
            "tense and suspenseful — use short, clipped sentences; incomplete thoughts; "
            "sensory hyperawareness (every sound amplified); the prose should feel like "
            "held breath; remove softening words; make every sentence a wire pulled taut"
        ),
        RephraseTone.WHIMSICAL: (
            "whimsical and playful — use unexpected word choices and surprising images; "
            "a light, dancing rhythm; gentle exaggeration; the prose should feel like "
            "it's winking at the reader; delight in language itself"
        ),
        RephraseTone.GROSS: (
            "visceral and uncomfortably vivid — use precise, unflinching physical detail; "
            "textures, smells, and sounds that make the reader squirm; don't look away; "
            "the prose should be felt in the body, not just read"
        ),
        RephraseTone.MYSTERIOUS: (
            "mysterious and enigmatic — withhold as much as you reveal; use implication "
            "over statement; shadows, half-seen things, unanswered questions; the prose "
            "should make the reader lean forward, uncertain but drawn in"
        ),
        RephraseTone.ROMANTIC: (
            "romantic and intimate — use closeness, breath, warmth, touch; slow the "
            "rhythm; let sentences linger on sensory detail; the prose should feel like "
            "two people in a room where no one else exists"
        ),
        RephraseTone.HUMOROUS: (
            "humorous and witty — use timing, understatement, and surprise; subvert "
            "expectations mid-sentence; dry observations; the humor should arise "
            "naturally from the situation, not from forced jokes"
        ),
        RephraseTone.OMINOUS: (
            "foreboding and ominous — the ordinary becomes threatening; use double "
            "meanings; innocuous details that feel wrong; the prose should create "
            "a sense that something terrible is approaching but not yet visible"
        ),
        RephraseTone.URGENT: (
            "urgent and pressing — use imperative energy; strip away all decoration; "
            "short sentences, no qualifiers; the prose should feel like running; "
            "every word must justify its existence; breathlessness"
        ),
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
        # MLX model attributes
        self._mlx_model = None
        self._mlx_tokenizer = None
        self._mlx_model_id = None

    def _get_huggingface_token(self) -> Optional[str]:
        """Get HuggingFace token from secure storage, config, or environment.

        Priority order:
        1. Credential manager (secure keyring storage)
        2. genai_config.json
        3. HF_TOKEN environment variable
        4. huggingface-cli login token

        Returns:
            HuggingFace token or None if not configured
        """
        import os

        # 1. Check credential manager (most secure, preferred method)
        try:
            from src.config.credential_manager import get_credential_manager
            cred_manager = get_credential_manager()
            token = cred_manager.get_huggingface_token()
            if token:
                # Mask token for security but show it was found
                masked = token[:4] + "..." + token[-4:] if len(token) > 8 else "***"
                print(f"  HuggingFace token found in credential manager: {masked}")
                return token
            else:
                print("  Credential manager: no token stored")
        except Exception as e:
            print(f"  Credential manager error: {type(e).__name__}: {e}")

        # 2. Check genai_config.json
        try:
            from src.config.genai_config import GenAIConfig
            config = GenAIConfig()
            token = config.get("huggingface_token", "")
            if token:
                print("  HuggingFace token found in genai_config.json")
                return token
        except Exception:
            pass

        # 3. Check environment variable
        token = os.environ.get("HF_TOKEN", "")
        if token:
            print("  HuggingFace token found in HF_TOKEN environment variable")
            return token

        # 4. Check huggingface-cli login (stored token)
        try:
            from huggingface_hub import HfFolder
            token = HfFolder.get_token()
            if token:
                print("  HuggingFace token found from huggingface-cli login")
                return token
        except Exception:
            pass

        print("  ⚠ No HuggingFace token found - gated models may fail to load")
        return None

    def _convert_to_mlx_model_id(self, model_id: str) -> str:
        """Convert a standard HuggingFace model ID to its MLX equivalent if available.

        Args:
            model_id: Original model ID (e.g., "Qwen/Qwen2.5-14B-Instruct")

        Returns:
            MLX model ID if available, otherwise returns original
        """
        # If already an MLX model, return as-is
        if model_id.startswith("mlx-community/"):
            return model_id

        # Map standard models to their MLX equivalents (4-bit quantized for performance)
        mlx_mapping = {
            # Qwen 2.5 series (Alibaba - excellent for general use)
            "Qwen/Qwen2.5-3B-Instruct": "mlx-community/Qwen2.5-3B-Instruct-4bit",
            "Qwen/Qwen2.5-7B-Instruct": "mlx-community/Qwen2.5-7B-Instruct-4bit",
            "Qwen/Qwen2.5-14B-Instruct": "mlx-community/Qwen2.5-14B-Instruct-4bit",
            "Qwen/Qwen2.5-32B-Instruct": "mlx-community/Qwen2.5-32B-Instruct-4bit",

            # Qwen 3 series (Latest January 2026)
            "Qwen/Qwen3-4B": "mlx-community/Qwen3-4B-4bit",
            "Qwen/Qwen3-8B": "mlx-community/Qwen3-8B-4bit",
            "Qwen/Qwen3-30B-A3B": "mlx-community/Qwen3-30B-A3B-4bit",

            # Gemma 3 series (Google - multimodal, works great on MLX!)
            "google/gemma-3-4b-it": "mlx-community/gemma-3-4b-it-4bit",
            "google/gemma-3-12b-it": "mlx-community/gemma-3-12b-it-4bit",
            "google/gemma-3-27b-it": "mlx-community/gemma-3-27b-it-4bit",

            # Mistral series (Mistral AI - excellent instruction following)
            "mistralai/Mistral-7B-Instruct-v0.3": "mlx-community/Mistral-7B-Instruct-v0.3-4bit",
            "mistralai/Mistral-Nemo-Instruct-2407": "mlx-community/Mistral-Nemo-Instruct-2407-4bit",
            "mistralai/Mistral-Small-Instruct-2409": "mlx-community/Mistral-Small-Instruct-2409-4bit",

            # Phi series (Microsoft - very efficient small models)
            "microsoft/Phi-3-mini-4k-instruct": "mlx-community/Phi-3-mini-4k-instruct-4bit",
            "microsoft/Phi-3.5-mini-instruct": "mlx-community/Phi-3.5-mini-instruct-4bit",
        }

        return mlx_mapping.get(model_id, model_id)

    def _convert_to_pytorch_model_id(self, model_id: str) -> str:
        """Convert an MLX model ID back to its PyTorch equivalent.

        Args:
            model_id: MLX model ID (e.g., "mlx-community/Qwen2.5-7B-Instruct-4bit")

        Returns:
            PyTorch model ID if MLX model, otherwise returns original
        """
        # If not an MLX model, return as-is
        if not model_id.startswith("mlx-community/"):
            return model_id

        # Reverse mapping: MLX -> PyTorch
        pytorch_mapping = {
            # Qwen 2.5 series
            "mlx-community/Qwen2.5-3B-Instruct-4bit": "Qwen/Qwen2.5-3B-Instruct",
            "mlx-community/Qwen2.5-7B-Instruct-4bit": "Qwen/Qwen2.5-7B-Instruct",
            "mlx-community/Qwen2.5-14B-Instruct-4bit": "Qwen/Qwen2.5-14B-Instruct",
            "mlx-community/Qwen2.5-32B-Instruct-4bit": "Qwen/Qwen2.5-32B-Instruct",

            # Qwen 3 series
            "mlx-community/Qwen3-4B-4bit": "Qwen/Qwen3-4B",
            "mlx-community/Qwen3-8B-4bit": "Qwen/Qwen3-8B",
            "mlx-community/Qwen3-30B-A3B-4bit": "Qwen/Qwen3-30B-A3B",

            # Gemma 3 series
            "mlx-community/gemma-3-4b-it-4bit": "google/gemma-3-4b-it",
            "mlx-community/gemma-3-12b-it-4bit": "google/gemma-3-12b-it",
            "mlx-community/gemma-3-27b-it-4bit": "google/gemma-3-27b-it",

            # Mistral series
            "mlx-community/Mistral-7B-Instruct-v0.3-4bit": "mistralai/Mistral-7B-Instruct-v0.3",
            "mlx-community/Mistral-Nemo-Instruct-2407-4bit": "mistralai/Mistral-Nemo-Instruct-2407",
            "mlx-community/Mistral-Small-Instruct-2409-4bit": "mistralai/Mistral-Small-Instruct-2409",

            # Phi series
            "mlx-community/Phi-3-mini-4k-instruct-4bit": "microsoft/Phi-3-mini-4k-instruct",
            "mlx-community/Phi-3.5-mini-instruct-4bit": "microsoft/Phi-3.5-mini-instruct",
        }

        return pytorch_mapping.get(model_id, model_id)

    def _init_mlx_model(self):
        """Initialize MLX model for Apple Silicon optimized inference.

        Uses a global cache to keep models loaded in memory across agent instances.
        Automatically converts standard HuggingFace model IDs to MLX equivalents.
        """
        if not _MLX_AVAILABLE:
            raise RuntimeError("MLX is not available")

        # Use model from settings, or fall back to default
        original_model_id = self.local_model_id or "Qwen/Qwen2.5-7B-Instruct"

        # Convert to MLX model if needed
        model_id = self._convert_to_mlx_model_id(original_model_id)

        if model_id != original_model_id:
            print(f"Converting to MLX model: {original_model_id} → {model_id}")

        # Check if model is already cached
        cached_model, cached_tokenizer = mlx_cache.get_model(model_id)
        if cached_model is not None:
            print(f"Using cached MLX model: {model_id}")
            self._mlx_model = cached_model
            self._mlx_tokenizer = cached_tokenizer
            self._mlx_model_id = model_id
            return

        # Check if instance already has this model loaded
        if self._mlx_model is not None:
            return

        try:
            import os
            print(f"\n{'='*60}")
            print(f"MLX MODEL INITIALIZATION")
            print(f"{'='*60}")
            print(f"Loading MLX model: {model_id}")

            # Get HuggingFace token for gated model access
            print("\n[Step 0] Checking HuggingFace token...")
            hf_token = self._get_huggingface_token()
            if hf_token:
                os.environ['HF_TOKEN'] = hf_token
                print("  HF_TOKEN environment variable set for mlx_lm")

            # Verify this is actually an MLX model
            if not model_id.startswith("mlx-community/"):
                print(f"⚠ Warning: Model ID doesn't start with 'mlx-community/'")
                print(f"  This may be a PyTorch model, not an MLX model.")
                print(f"  Attempting to load anyway...")

            model, tokenizer = None, None

            # Try mlx_lm first (text-only models)
            try:
                from mlx_lm import load
                print("  Loading with mlx_lm...")
                model, tokenizer = load(model_id)
                print(f"[OK] MLX model loaded via mlx_lm")
            except Exception as mlx_lm_err:
                err_str = str(mlx_lm_err)
                if "not supported" in err_str.lower() or "model type" in err_str.lower():
                    # Model type not in mlx_lm — try mlx_vlm which supports
                    # newer architectures like gemma4
                    print(f"  mlx_lm does not support this model type: {err_str}")
                    print(f"  Trying mlx_vlm...")
                    try:
                        from mlx_vlm import load as vlm_load
                        model, tokenizer = vlm_load(model_id)
                        print(f"[OK] MLX model loaded via mlx_vlm")
                    except ImportError:
                        raise RuntimeError(
                            f"Model type not supported by mlx_lm. "
                            f"Install mlx_vlm for Gemma 4 support:\n"
                            f"  pip install --upgrade mlx-vlm"
                        )
                else:
                    raise

            if model is None:
                raise RuntimeError(f"Failed to load model: no loader succeeded")

            # Store in instance
            self._mlx_model = model
            self._mlx_tokenizer = tokenizer
            self._mlx_model_id = model_id

            # Cache for future use
            mlx_cache.set_model(model_id, model, tokenizer)
            print(f"[OK] MLX model cached for reuse")
            print(f"{'='*60}\n")

        except Exception as e:
            error_msg = str(e)
            print(f"[FAIL] MLX model loading failed!")
            print(f"  Error: {error_msg}")

            # Provide helpful error messages
            if "ignore_mismatched_sizes" in error_msg:
                print(f"\n  💡 This error suggests you're trying to load a PyTorch model with MLX.")
                print(f"     Model ID: {model_id}")
                print(f"     Solution: Use an MLX-compatible model ID starting with 'mlx-community/'")
            elif "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                print(f"\n  💡 Model not found. It will be downloaded on first use.")
                print(f"     Ensure you have internet connection and disk space.")

            print(f"{'='*60}\n")
            raise RuntimeError(f"Failed to load MLX model '{model_id}': {error_msg}")

    def _init_local_model(self):
        """Initialize local small language model.

        Uses a global cache to keep models loaded in memory across agent instances.
        Only reloads if a different model is requested.
        """
        global _cuda_failed
        # Use model from settings, or fall back to default
        original_model_id = self.local_model_id or "microsoft/Phi-3-mini-4k-instruct"

        # Convert MLX model IDs to PyTorch equivalents for PyTorch backend
        # This is important when falling back from MLX to PyTorch
        model_id = self._convert_to_pytorch_model_id(original_model_id)

        # Prominent logging at the very start
        print(f"\n{'#'*60}")
        print(f"# MODEL INITIALIZATION STARTING")
        print(f"{'#'*60}")
        print(f"📦 Model ID: {model_id}")
        print(f"⏰ Start time: {time.strftime('%H:%M:%S')}")
        print(f"{'#'*60}\n")

        if model_id != original_model_id:
            print(f"Converted MLX model to PyTorch equivalent:")
            print(f"  MLX: {original_model_id}")
            print(f"  PyTorch: {model_id}")

        # Check if model is already cached
        cached_model, cached_tokenizer, cached_device = _model_cache.get_model(model_id)
        if cached_model is not None:
            # If CUDA previously failed, move cached model to CPU
            if _cuda_failed and cached_device == "cuda":
                print(f"\n⚠️  CACHED MODEL FOUND but CUDA failed previously — moving to CPU...")
                import torch
                cached_model = cached_model.to("cpu")
                cached_device = "cpu"
                _model_cache.set_model(model_id, cached_model, cached_tokenizer, "cpu")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                print(f"[OK] Model moved to CPU")
            else:
                print(f"\n✅ CACHED MODEL FOUND - INSTANT LOAD!")
            print(f"📦 Model: {model_id}")
            print(f"🖥️  Device: {cached_device.upper()}")
            print(f"{'='*60}\n")
            self._local_model = cached_model
            self._local_tokenizer = cached_tokenizer
            self._device = cached_device
            return

        # Check if instance already has this model loaded
        if self._local_model is not None:
            print(f"✅ Model already loaded in this instance")
            return

        print(f"⚠️  Model not cached - will download/load (this may take 30-120 seconds)")
        print(f"{'='*60}\n")

        try:
            print("\n[Imports Check]")
            print(f"  _TORCH_AVAILABLE: {_TORCH_AVAILABLE}")
            print(f"  _TRANSFORMERS_AVAILABLE: {_TRANSFORMERS_AVAILABLE}")

            if not _TORCH_AVAILABLE:
                error_details = f"\nOriginal error: {_TORCH_IMPORT_ERROR}" if _TORCH_IMPORT_ERROR else ""
                raise RuntimeError(
                    f"PyTorch is not available.{error_details}\n"
                    f"Install with: pip install torch\n"
                    f"Python executable: {sys.executable}"
                )

            import torch  # Ensure torch is in local scope for all fallback paths

            if not _TRANSFORMERS_AVAILABLE:
                error_details = f"\nOriginal error: {_TRANSFORMERS_IMPORT_ERROR}" if _TRANSFORMERS_IMPORT_ERROR else ""
                raise ImportError(
                    f"Transformers failed to import at module level.{error_details}\n\n"
                    "This usually means:\n"
                    "1. transformers is not installed: pip install transformers\n"
                    "2. Python environment mismatch (check you're using .venv)\n"
                    "3. Package installation corrupted (try reinstalling)\n\n"
                    f"Python executable: {sys.executable}"
                )

            print(f"  Using module-level imports (transformers already available)")
            # Use the module-level imports
            if AutoModelForCausalLM is None or AutoTokenizer is None:
                raise ImportError("transformers imported but classes are None - this should not happen")

            # Increase recursion limit to prevent stack overflow during model loading
            # Gemma3 and other models with complex architectures need very high recursion limits
            old_recursion_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(10000)  # Temporarily increase from default 1000 (Gemma3 needs ~10000)

            try:
                init_start_time = time.time()

                print(f"\n{'='*60}")
                print(f"DETAILED INITIALIZATION LOG")
                print(f"{'='*60}")
                print(f"Model: {model_id}")
                print(f"Recursion limit: {sys.getrecursionlimit()}")

                # Get HuggingFace token for gated model access
                print("\n[Step 0] Checking HuggingFace token...")
                step_start = time.time()
                hf_token = self._get_huggingface_token()
                print(f"[OK] Token check complete ({time.time() - step_start:.2f}s)")

                print("\n[Step 1] Loading tokenizer...")
                step_start = time.time()
                tokenizer = AutoTokenizer.from_pretrained(
                    model_id,
                    token=hf_token
                )
                print(f"[OK] Tokenizer loaded ({time.time() - step_start:.2f}s)")
                # Ensure pad_token is set (required for Gemma and some other models)
                if tokenizer.pad_token is None:
                    tokenizer.pad_token = tokenizer.eos_token
                    print(f"  Set pad_token to eos_token: {tokenizer.pad_token}")

                # Use shared device detection utility for cross-platform support
                print("\n[Step 2] Detecting hardware...")
                step_start = time.time()
                print_device_info()
                device_name, dtype, use_device_map = detect_device()

                # If CUDA previously failed with an assertion, force CPU
                if _cuda_failed and device_name == "cuda":
                    print("  ** CUDA previously failed with assertion error — forcing CPU **")
                    device_name = "cpu"
                    use_device_map = False
                    import torch
                    dtype = torch.float32
                print(f"\n🖥️  HARDWARE DETECTED:")
                print(f"  Device: {device_name.upper()}")
                print(f"  Data type: {dtype}")
                print(f"  Device map: {use_device_map}")
                if device_name == "cuda":
                    import torch
                    gpu_name = torch.cuda.get_device_name(0)
                    gpu_mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                    print(f"  GPU: {gpu_name}")
                    print(f"  VRAM: {gpu_mem_gb:.1f} GB")
                print(f"[OK] Hardware detection complete ({time.time() - step_start:.2f}s)")

                model = None
                device = device_name

                # Load model with appropriate settings for the detected device
                try:
                    print(f"\n[Step 3] Loading model weights on {device_name}...")
                    step_start = time.time()

                    model_kwargs = {
                        "dtype": dtype,
                        "attn_implementation": "eager",  # Use eager attention to avoid flash attention recursion
                        "token": hf_token,  # For gated model access (e.g., Gemma)
                    }

                    # Only use device_map for CUDA (don't combine with low_cpu_mem_usage)
                    if use_device_map and device_name == "cuda":
                        model_kwargs["device_map"] = "auto"
                        print("  - Using device_map='auto' (CUDA multi-GPU)")
                    else:
                        # Use low_cpu_mem_usage only when NOT using device_map
                        model_kwargs["low_cpu_mem_usage"] = True
                        print(f"  - No device_map (will use .to('{device_name}'))")

                    print(f"  - Model kwargs: {list(model_kwargs.keys())}")
                    print(f"\n⏳ LOADING MODEL WEIGHTS FROM HUGGINGFACE...")
                    print(f"   This step typically takes 30-120 seconds depending on:")
                    print(f"   - Whether model needs to be downloaded (first time)")
                    print(f"   - Your disk speed (SSD vs HDD)")
                    print(f"   - Model size (Phi 3.5 Mini is ~7.6GB)")
                    print(f"\n⏰ Started at: {time.strftime('%H:%M:%S')}")
                    print(f"   Please wait...\n")

                    model = AutoModelForCausalLM.from_pretrained(
                        model_id,
                        **model_kwargs
                    )
                    loading_time = time.time() - step_start
                    print(f"\n[OK] Model weights loaded: {type(model).__name__}")
                    print(f"⏱️  Loading took {loading_time:.1f} seconds")

                    # Check for meta tensors (model not properly loaded)
                    has_meta = any(p.device.type == "meta" for p in model.parameters())
                    if has_meta:
                        print("⚠ Model has meta tensors - reloading without device_map...")
                        step_start = time.time()
                        del model
                        torch.cuda.empty_cache()

                        # Reload without device_map, then move to CUDA
                        model = AutoModelForCausalLM.from_pretrained(
                            model_id,
                            dtype=dtype,
                            low_cpu_mem_usage=True,
                            attn_implementation="eager",
                            token=hf_token,
                        )
                        model = model.to(device_name)
                        print(f"[OK] Model reloaded and moved to {device_name} ({time.time() - step_start:.1f}s)")
                    elif not use_device_map:
                        # Explicitly move to device if not using device_map
                        print(f"\n[Step 4] Moving model to {device_name}...")
                        step_start = time.time()
                        model = model.to(device_name)
                        print(f"[OK] Model moved to {device_name} ({time.time() - step_start:.1f}s)")

                    total_init_time = time.time() - init_start_time
                    print(f"\n{'#'*60}")
                    print(f"# ✅ INITIALIZATION COMPLETE")
                    print(f"{'#'*60}")
                    print(f"📦 Model: {model_id}")
                    print(f"🖥️  Device: {device_name.upper()}")
                    print(f"⏱️  Total time: {total_init_time:.1f}s")
                    print(f"💾 Status: Now cached for instant future use")
                    print(f"{'#'*60}\n")

                except Exception as e:
                    error_str = str(e).lower()
                    print(f"{device_name} loading failed: {type(e).__name__}: {e}")

                    # Check if it's an out of memory error
                    is_oom = "out of memory" in error_str or "cuda out of memory" in error_str

                    if is_oom and device_name == "cuda":
                        # Get GPU memory info
                        try:
                            gpu_mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                            print(f"\n⚠ GPU has {gpu_mem_gb:.1f}GB VRAM - model is too large!")
                            print(f"  Model: {model_id}")
                            print(f"\n  Recommended models for {gpu_mem_gb:.0f}GB VRAM:")
                            if gpu_mem_gb < 12:
                                print(f"    • microsoft/Phi-3.5-mini-instruct (~6GB)")
                                print(f"    • google/gemma-3-4b-it (~8GB)")
                            elif gpu_mem_gb < 20:
                                print(f"    • google/gemma-3-4b-it (~8GB)")
                                print(f"    • Qwen/Qwen2.5-7B-Instruct (~14GB)")
                                print(f"    • microsoft/Phi-3.5-mini-instruct (~6GB)")
                            else:
                                print(f"    • Qwen/Qwen2.5-14B-Instruct (~28GB)")
                                print(f"    • google/gemma-3-12b-it (~24GB)")
                        except Exception:
                            pass

                        # Try CPU offloading (keeps some layers on GPU, rest on CPU/disk)
                        print("\nAttempting CPU offloading...")
                        torch.cuda.empty_cache()

                        try:
                            model = AutoModelForCausalLM.from_pretrained(
                                model_id,
                                dtype=dtype,
                                device_map="auto",
                                offload_folder="offload",
                                attn_implementation="eager",
                                token=hf_token,
                            )
                            has_meta = any(p.device.type == "meta" for p in model.parameters())
                            if has_meta:
                                raise RuntimeError("Model has uninitialized meta tensors")
                            device = "cuda"
                            print(f"[OK] Model loaded with CPU offloading (slower but works)")
                        except Exception as offload_err:
                            print(f"CPU offloading failed: {offload_err}")
                            print("\nFalling back to CPU-only...")

                            torch.cuda.empty_cache()
                            model = AutoModelForCausalLM.from_pretrained(
                                model_id,
                                dtype=torch.float32,
                                low_cpu_mem_usage=True,
                                attn_implementation="eager",
                                token=hf_token
                            )
                            model = model.to("cpu")
                            device = "cpu"
                            print("[OK] Model loaded on CPU (will be slow)")

                    elif device_name != "cpu":
                        print("Falling back to CPU...")
                        try:
                            if device_name == "cuda":
                                torch.cuda.empty_cache()

                            model = AutoModelForCausalLM.from_pretrained(
                                model_id,
                                dtype=torch.float32,
                                low_cpu_mem_usage=True,
                                attn_implementation="eager",
                                token=hf_token
                            )
                            model = model.to("cpu")
                            device = "cpu"
                            print("Model loaded on CPU (fallback)")

                        except Exception as cpu_err:
                            print(f"CPU fallback also failed: {type(cpu_err).__name__}: {cpu_err}")
                            raise
                    else:
                        raise

                # Store in instance
                self._local_model = model
                self._local_tokenizer = tokenizer
                self._device = device

                # Cache for future use
                print(f"💾 Caching model for future use...")
                _model_cache.set_model(model_id, model, tokenizer, device)
                print(f"[OK] Model cached - next load will be instant!")

            finally:
                # Always restore original recursion limit
                sys.setrecursionlimit(old_recursion_limit)

        except ImportError:
            raise ImportError(
                "Local model requires transformers and torch. "
                "Install with: pip install transformers torch"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load local model: {e}")

    def _generate_mlx(self, prompt: str, max_tokens: int = 500) -> str:
        """Generate text using MLX (Apple Silicon optimized)."""
        if not _MLX_AVAILABLE:
            raise RuntimeError("MLX is not available")

        print(f"\n{'='*60}")
        print(f"MLX GENERATION - Apple Silicon Optimized")
        print(f"{'='*60}")

        try:
            print("\n[1/4] Initializing MLX model...")
            self._init_mlx_model()
            print(f"[OK] MLX model initialized: {self._mlx_model_id}")

            print("\n[2/4] Preparing prompt...")
            messages = [
                {"role": "system", "content": self.REPHRASE_SYSTEM},
                {"role": "user", "content": prompt}
            ]

            # Apply chat template manually for MLX
            prompt_text = self._mlx_tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            print(f"[OK] Prompt prepared ({len(prompt_text)} chars)")

            print("\n[3/4] Generating with MLX...")
            print(f"  Parameters:")
            print(f"    - max_tokens: {max_tokens}")
            print(f"    - temp: 0.7")

            # Track generation time
            gen_start_time = time.time()
            print(f"  ⏱️  Starting generation at {time.strftime('%H:%M:%S')}...")

            # Try mlx_lm.generate first, fall back to mlx_vlm.generate
            # for newer architectures (gemma4, etc.)
            try:
                from mlx_lm import generate as mlx_generate
                from mlx_lm.sample_utils import make_sampler
                sampler = make_sampler(temp=0.7)
                response = mlx_generate(
                    self._mlx_model,
                    self._mlx_tokenizer,
                    prompt=prompt_text,
                    max_tokens=max_tokens,
                    sampler=sampler,
                    verbose=False
                )
            except Exception:
                from mlx_vlm import generate as vlm_generate
                response = vlm_generate(
                    self._mlx_model,
                    self._mlx_tokenizer,
                    prompt_text,
                    max_tokens=max_tokens,
                    temp=0.7,
                    verbose=False
                )

            # Calculate and log generation time
            gen_end_time = time.time()
            gen_elapsed = gen_end_time - gen_start_time
            print(f"[OK] Generation complete!")
            print(f"  ⏱️  Generation took {gen_elapsed:.2f} seconds")

            print(f"\n[4/4] Extracting response...")
            # mlx_vlm.generate returns a GenerationResult object, not a string
            if not isinstance(response, str):
                response = getattr(response, 'text', '') or str(response)
            # Extract just the generated part (remove the prompt)
            if response.startswith(prompt_text):
                response = response[len(prompt_text):].strip()

            print(f"[OK] Response extracted ({len(response)} chars)")

            print(f"\n{'='*60}")
            print(f"✅ GENERATION COMPLETE (MLX)")
            print(f"{'='*60}")
            print(f"📦 Model: {self._mlx_model_id}")
            print(f"🖥️  Device: MPS (Apple Silicon)")
            print(f"⏱️  Time: {gen_elapsed:.2f}s")
            print(f"📝 Output: {len(response)} chars")
            print(f"{'='*60}\n")

            return response

        except Exception as e:
            print(f"[FAIL] MLX generation failed: {e}")
            raise

    def _generate_local(self, prompt: str, max_tokens: int = 500) -> str:
        """Generate text using local model (PyTorch or MLX).

        Automatically selects the best backend:
        - Apple Silicon: Tries MLX first (faster), falls back to PyTorch
        - Other platforms: Uses PyTorch
        """
        global _cuda_failed
        # Determine backend and device info upfront
        backend = "MLX" if (_MLX_AVAILABLE and can_use_mlx()) else "PyTorch"
        device = "Unknown"

        if backend == "PyTorch":
            # Check current device or detect it
            if hasattr(self, '_device') and self._device:
                device = self._device.upper()
            else:
                from src.ai.device_utils import detect_device
                device_name, _, _ = detect_device()
                device = device_name.upper()
        else:
            device = "MPS (Apple Silicon)"

        # Check if model is cached
        is_cached = False
        if backend == "MLX":
            from src.ai.mlx_utils import get_mlx_cache
            cache = get_mlx_cache()
            is_cached = cache.is_loaded(self.local_model_id)
        else:
            is_cached = (hasattr(self, '_local_model') and self._local_model is not None and
                        hasattr(self, '_cached_model_id') and self._cached_model_id == self.local_model_id)

        # Log model request summary with prominent device info
        print(f"\n{'='*60}")
        print(f"🤖 LOCAL MODEL GENERATION")
        print(f"{'='*60}")
        print(f"📦 Model: {self.local_model_id or '(not set)'}")
        print(f"⚙️  Backend: {backend}")
        print(f"🖥️  Device: {device}")
        print(f"💾 Cached: {'Yes (instant)' if is_cached else 'No (loading...)'}")
        print(f"📊 Max tokens: {max_tokens}")
        print(f"📝 Prompt: {len(prompt)} chars")
        print(f"{'='*60}\n")

        # Prefer MLX on Apple Silicon for better performance
        if _MLX_AVAILABLE and can_use_mlx():
            try:
                return self._generate_mlx(prompt, max_tokens)
            except Exception as mlx_error:
                # If the model is MLX-only (mlx-community/ or unsloth/..MLX),
                # don't fall back to PyTorch — it can't load MLX-quantized weights
                model_lower = (self.local_model_id or "").lower()
                is_mlx_only = (
                    "mlx-community/" in model_lower
                    or "mlx" in model_lower.split("/")[-1]
                )
                if is_mlx_only:
                    raise RuntimeError(
                        f"MLX generation failed for '{self.local_model_id}': {mlx_error}\n\n"
                        f"This is an MLX-only model and cannot fall back to PyTorch.\n"
                        f"Try: pip install --upgrade mlx mlx-lm mlx-vlm"
                    )

                print(f"⚠ MLX generation failed: {mlx_error}")
                print("  Falling back to PyTorch...")

                if not _TORCH_AVAILABLE:
                    raise RuntimeError(f"MLX failed and PyTorch not available: {mlx_error}")

        if not _TORCH_AVAILABLE:
            raise RuntimeError("Neither MLX nor PyTorch is available for local inference")

        print(f"\n{'='*60}")
        print(f"LOCAL MODEL GENERATION - DEBUG LOG")
        print(f"{'='*60}")
        print(f"Initial recursion limit: {sys.getrecursionlimit()}")

        # Increase recursion limit for generation as well
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(10000)  # Even higher for generation
        print(f"Increased recursion limit to: {sys.getrecursionlimit()}")

        try:
            print("\n[1/7] Initializing local model...")
            self._init_local_model()
            print(f"[OK] Model initialized on device: {self._device}")
            print(f"  Model class: {type(self._local_model).__name__}")

            print("\n[2/7] Preparing messages...")
            # Check if tokenizer supports system role (Gemma 3 doesn't)
            model_id_lower = (self.local_model_id or "").lower()
            supports_system_role = "gemma" not in model_id_lower

            if supports_system_role:
                messages = [
                    {"role": "system", "content": self.REPHRASE_SYSTEM},
                    {"role": "user", "content": prompt}
                ]
            else:
                # For Gemma 3: embed system prompt in user message
                combined_prompt = f"{self.REPHRASE_SYSTEM}\n\n{prompt}"
                messages = [
                    {"role": "user", "content": combined_prompt}
                ]
                print("  (Gemma detected - embedding system prompt in user message)")
            print(f"[OK] Messages prepared (prompt: {len(prompt)} chars)")

            print("\n[3/7] Applying chat template...")

            # Check if tokenizer has a chat template
            has_chat_template = hasattr(self._local_tokenizer, 'chat_template') and self._local_tokenizer.chat_template is not None

            if has_chat_template:
                # Use the model's chat template
                result = self._local_tokenizer.apply_chat_template(
                    messages,
                    return_tensors="pt",
                    add_generation_prompt=True
                )
                # Extract input_ids if result is a BatchEncoding, otherwise use directly
                if hasattr(result, 'input_ids'):
                    inputs = result.input_ids
                    print(f"[OK] Template applied (BatchEncoding -> extracted input_ids)")
                else:
                    inputs = result
                    print(f"[OK] Template applied (got tensor directly)")

                if hasattr(inputs, 'shape'):
                    print(f"  Shape: {inputs.shape}, tokens: {inputs.shape[1]}")
                else:
                    print(f"  Warning: unexpected type: {type(inputs)}")
            else:
                # Fallback: manually format prompt for models without chat templates
                print("  ⚠ Model has no chat template - using simple prompt format")

                # Simple formatting for non-chat models
                if supports_system_role and len(messages) > 1:
                    formatted_prompt = f"{messages[0]['content']}\n\n{messages[1]['content']}"
                else:
                    formatted_prompt = messages[0]['content']

                # Tokenize directly
                inputs = self._local_tokenizer(
                    formatted_prompt,
                    return_tensors="pt",
                    truncation=True,
                    max_length=2048
                )["input_ids"]
                print(f"[OK] Prompt tokenized (shape: {inputs.shape}, tokens: {inputs.shape[1]})")

            print("\n[4/7] Creating attention mask...")
            # Create attention mask (1 for all tokens since there's no padding)
            attention_mask = torch.ones_like(inputs)
            print(f"[OK] Attention mask created (shape: {attention_mask.shape})")

            print("\n[5/7] Moving tensors to device...")
            # Move inputs to the same device as the model
            if hasattr(self, '_device') and self._device:
                print(f"  Moving to {self._device}...")
                inputs = inputs.to(self._device)
                attention_mask = attention_mask.to(self._device)
                print(f"[OK] Tensors moved to {self._device}")
            elif hasattr(self._local_model, 'device'):
                device = self._local_model.device
                print(f"  Moving to {device}...")
                inputs = inputs.to(device)
                attention_mask = attention_mask.to(device)
                print(f"[OK] Tensors moved to {device}")

            # Limit input length to prevent excessive memory/computation
            max_input_length = 2048
            if inputs.shape[1] > max_input_length:
                print(f"⚠ Warning: Input too long ({inputs.shape[1]} tokens), truncating to {max_input_length}")
                inputs = inputs[:, -max_input_length:]
                attention_mask = attention_mask[:, -max_input_length:]

            # CRITICAL: Validate token IDs are within vocabulary range
            vocab_size = self._local_model.config.vocab_size
            max_token_id = inputs.max().item()
            min_token_id = inputs.min().item()
            print(f"\n[Token Validation]")
            print(f"  Model vocab size: {vocab_size}")
            print(f"  Input token range: {min_token_id} to {max_token_id}")

            if max_token_id >= vocab_size:
                error_msg = (
                    f"Token ID out of range! Max token ID ({max_token_id}) >= vocab size ({vocab_size})\n"
                    f"This means the tokenizer and model are incompatible.\n"
                    f"Model: {self._local_model_id}\n"
                    f"Solution: Try a different model that doesn't require trust_remote_code"
                )
                print(f"[FAIL] {error_msg}")
                raise ValueError(error_msg)

            if min_token_id < 0:
                error_msg = f"Invalid negative token ID: {min_token_id}"
                print(f"[FAIL] {error_msg}")
                raise ValueError(error_msg)

            print(f"[OK] Token IDs are valid")

            print(f"\n[6/7] Calling model.generate()...")
            print(f"  Parameters:")
            print(f"    - max_new_tokens: {max_tokens}")
            print(f"    - temperature: 0.7")
            print(f"    - do_sample: True")
            print(f"    - use_cache: True")
            print(f"    - num_beams: 1")
            print(f"    - attn_implementation: eager")

            # Track generation time
            gen_start_time = time.time()
            print(f"  ⏱️  Starting generation at {time.strftime('%H:%M:%S')}...")

            # Use pad_token_id from tokenizer (we set it during init if it was None)
            pad_token_id = self._local_tokenizer.pad_token_id
            if pad_token_id is None:
                pad_token_id = self._local_tokenizer.eos_token_id

            # Check if this is a model with known CUDA assertion issues
            model_id_lower = (self.local_model_id or "").lower()
            is_cuda_fragile = any(k in model_id_lower for k in ("gemma", "qwen"))

            # If CUDA previously failed, proactively move everything to CPU now
            # (before generation, not after crash)
            if _cuda_failed and self._device == "cuda":
                print("  ** CUDA previously poisoned — moving model and tensors to CPU before generation **")
                try:
                    self._local_model = self._local_model.to("cpu")
                    inputs = inputs.to("cpu")
                    attention_mask = attention_mask.to("cpu")
                    self._device = "cpu"
                    _model_cache.set_model(self._model_id, self._local_model, self._local_tokenizer, "cpu")
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    print("  [OK] Moved to CPU")
                except Exception as move_err:
                    print(f"  [WARN] Could not move to CPU: {move_err}")

            try:
                # Build generation kwargs
                gen_kwargs = {
                    "attention_mask": attention_mask,
                    "max_new_tokens": max_tokens,
                    "pad_token_id": pad_token_id,
                    "eos_token_id": self._local_tokenizer.eos_token_id,
                    "use_cache": True,  # Enable KV cache for fast generation (critical for long outputs)
                    "num_beams": 1,  # Disable beam search to reduce complexity
                }

                if is_cuda_fragile:
                    # Known fragile models (Gemma, Qwen): use greedy decoding to avoid
                    # CUDA assertion errors and invalid generation flag warnings
                    print(f"  (Fragile model detected: using greedy decoding)")
                    gen_kwargs["do_sample"] = False
                else:
                    # Other models: use sampling with temperature
                    gen_kwargs["do_sample"] = True
                    gen_kwargs["temperature"] = 0.7
                    gen_kwargs["top_k"] = 50  # Limit sampling to top 50 tokens
                    gen_kwargs["top_p"] = 0.95  # Nucleus sampling

                outputs = self._local_model.generate(inputs, **gen_kwargs)

            except RuntimeError as e:
                error_str = str(e).lower()
                if "cuda" in error_str and ("assert" in error_str or "device-side" in error_str):
                    print(f"[FAIL] CUDA assertion error detected!")
                    print(f"  Error: {e}")

                    # Mark CUDA as failed globally so all future calls skip to CPU
                    _cuda_failed = True

                    # CUDA context is corrupted after assertion — must fall back to CPU
                    print(f"  CUDA context is poisoned after assertion. Falling back to CPU...")
                    try:
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()

                        # Move model and tensors to CPU
                        cpu_model = self._local_model.to("cpu")
                        cpu_inputs = inputs.to("cpu")
                        cpu_mask = attention_mask.to("cpu")

                        outputs = cpu_model.generate(
                            cpu_inputs,
                            attention_mask=cpu_mask,
                            max_new_tokens=max_tokens,
                            pad_token_id=pad_token_id,
                            eos_token_id=self._local_tokenizer.eos_token_id,
                            do_sample=False,  # Greedy decoding on CPU
                            use_cache=True,
                            num_beams=1,
                        )
                        # Keep model on CPU for this session to avoid further CUDA errors
                        self._local_model = cpu_model
                        self._device = "cpu"
                        # Update global cache so new agent instances get the CPU model
                        _model_cache.set_model(self._model_id, cpu_model, self._local_tokenizer, "cpu")
                        print(f"  [OK] CPU fallback succeeded! Model will stay on CPU for this session.")
                    except Exception as retry_error:
                        print(f"  [FAIL] CPU fallback also failed: {retry_error}")
                        print(f"\n  Suggestions:")
                        print(f"    1. Try a different model (e.g., TinyLlama/TinyLlama-1.1B-Chat-v1.0)")
                        print(f"    2. Restart the application to reset CUDA state")
                        raise
                else:
                    raise

            # Calculate and log generation time
            gen_end_time = time.time()
            gen_elapsed = gen_end_time - gen_start_time
            print(f"[OK] Generation complete! (output shape: {outputs.shape})")
            print(f"  ⏱️  Generation took {gen_elapsed:.2f} seconds")

            print(f"\n[7/7] Decoding output...")
        finally:
            print(f"\nRestoring recursion limit to: {old_limit}")
            sys.setrecursionlimit(old_limit)

        response = self._local_tokenizer.decode(
            outputs[0][inputs.shape[1]:],
            skip_special_tokens=True
        )
        print(f"[OK] Decoded {len(response)} characters (raw)")
        print(f"  Raw preview: {repr(response[:200])}")

        # Clean response: strip echoed prompt content that small models often generate
        response = self._clean_model_response(response, prompt)

        print(f"[OK] Cleaned response: {len(response)} characters")
        print(f"  Clean preview: {repr(response[:200])}")
        if not response.strip():
            print(f"  Warning: Response is empty or only whitespace!")

        print(f"\n{'='*60}")
        print(f"[OK] GENERATION COMPLETE")
        print(f"{'='*60}")
        print(f"Model: {self.local_model_id}")
        print(f"Device: {self._device.upper() if hasattr(self, '_device') else 'Unknown'}")
        print(f"Time: {gen_elapsed:.2f}s")
        print(f"Output: {len(response)} chars")
        print(f"{'='*60}\n")

        return response

    def _clean_model_response(self, response: str, prompt: str) -> str:
        """Clean model response by removing echoed prompt content.

        Small models often echo back parts of the prompt before giving
        their actual response. This method strips that noise.

        Args:
            response: Raw model output (after input token removal)
            prompt: The original prompt sent to the model

        Returns:
            Cleaned response with only the AI's actual output
        """
        if not response or not response.strip():
            return response

        original = response

        # Strategy 1: If response starts with the prompt (or large portion), strip it
        # Check if first 50+ chars of response match the prompt
        prompt_stripped = prompt.strip()
        response_stripped = response.strip()

        if len(prompt_stripped) > 50:
            # Check if response starts with the beginning of the prompt
            check_len = min(80, len(prompt_stripped))
            prompt_start = prompt_stripped[:check_len]
            if response_stripped.startswith(prompt_start):
                # Find where the prompt ends in the response
                # Look for the prompt content and skip past it
                prompt_len = len(prompt_stripped)
                if len(response_stripped) > prompt_len:
                    response = response_stripped[prompt_len:].strip()
                    print(f"  [Clean] Stripped echoed prompt ({prompt_len} chars)")

        # Strategy 2: Remove known prompt markers that shouldn't be in the response
        prompt_markers = [
            'Please rephrase the following text',
            'Original text:',
            'Generate these variations:',
            'For each variation, provide:',
            'Format your response as:',
            'Apply a',
            'PLOT OUTLINE:',
            'MAIN CHARACTERS:',
            'WORLDBUILDING:',
            'CURRENT CHAPTER OUTLINE:',
            'USER QUESTION:',
            'INSTRUCTIONS:',
            'TASK:',
            'ANALYSIS REQUESTED:',
            'PLANNED EVENTS:',
            'CHAPTER DRAFT:',
        ]

        lines = response.split('\n')
        clean_start = 0
        found_content = False

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            # Check if this line is part of an echoed prompt
            is_prompt_echo = False
            for marker in prompt_markers:
                if stripped.startswith(marker) or stripped == marker.rstrip(':'):
                    is_prompt_echo = True
                    break

            # Check for numbered instruction lines from the prompt (e.g. "1. Clearer and easier...")
            if not is_prompt_echo and stripped and stripped[0].isdigit() and '. ' in stripped[:4]:
                # Could be a prompt instruction line or an actual OPTION line
                # If it contains style keywords from prompt, skip it
                style_keywords = ['tone', 'easier to understand', 'more detailed', 'poetic and lyrical']
                if any(kw in stripped.lower() for kw in style_keywords):
                    is_prompt_echo = True

            # Check for separator lines
            if not is_prompt_echo and all(c in '=-_*' for c in stripped) and len(stripped) > 10:
                is_prompt_echo = True

            if is_prompt_echo:
                clean_start = i + 1
                continue

            # Found real content - check if it looks like an actual response
            if stripped.upper().startswith('OPTION') or stripped.startswith('1.') or stripped.startswith('Here'):
                found_content = True
                clean_start = i
                break

            # If we've been skipping echoed content and hit something new, start here
            if clean_start > 0:
                found_content = True
                clean_start = i
                break

            # If first line doesn't match any marker, it's probably real content
            found_content = True
            break

        if clean_start > 0:
            response = '\n'.join(lines[clean_start:]).strip()
            print(f"  [Clean] Skipped {clean_start} echoed prompt lines")

        # Strategy 3: If the response still contains quoted original text at the start, skip it
        if response.strip().startswith('"') and '"' in response[1:]:
            # Response starts with a quoted string - might be echoed original text
            end_quote = response.index('"', 1) + 1
            remaining = response[end_quote:].strip()
            # Only strip if there's substantial content after the quote
            if len(remaining) > 50:
                response = remaining
                print(f"  [Clean] Stripped quoted echo at start")

        return response.strip() if response else original

    def _build_style_tone_instruction(
        self,
        style: RephraseStyle,
        tone: RephraseTone = None,
        tones: Optional[List[RephraseTone]] = None
    ) -> str:
        """Build a combined instruction for style and one or more tones."""
        style_desc = self.STYLE_PROMPTS.get(style, "")

        # Resolve tone list
        if tones is None:
            tones = [tone] if tone is not None else []
        active = [t for t in tones if t and t != RephraseTone.NEUTRAL]
        tone_descs = [self.TONE_PROMPTS[t] for t in active if self.TONE_PROMPTS.get(t)]

        if len(tone_descs) == 1:
            tone_label = tone_descs[0]
        elif len(tone_descs) > 1:
            tone_label = " + ".join(tone_descs)
        else:
            tone_label = ""

        if tone_label and style_desc:
            return f"{style_desc} with a {tone_label} tone"
        elif tone_label:
            return f"with a {tone_label} tone"
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
        tone: RephraseTone = None,           # kept for back-compat (single tone)
        tones: Optional[List[RephraseTone]] = None,  # preferred: list of tones to blend
        custom_tone: str = "",               # free-text tone from the user
        context: str = "",
        num_options: int = 4,
        pov: str = "",                       # narrative point of view
        character_context: str = "",         # POV character details
        scene_description: str = "",         # what's happening in the scene
        surrounding_before: str = "",        # text before the selection
        surrounding_after: str = "",         # text after the selection
    ) -> RephraseResult:
        """Generate multiple rephrasing options for text.

        Args:
            text: Text to rephrase
            styles: Optional list of specific styles to generate
            tone: Single tone (legacy — use ``tones`` for multi-emotion blending)
            tones: List of tones to blend (e.g. [HAPPY, NOSTALGIC]); takes priority over ``tone``
            custom_tone: Free-text tone description typed by the user (e.g. "bittersweet")
            context: Optional context about the text (character, scene, etc.)
            num_options: Number of options to generate if no styles specified
            pov: Narrative point of view (e.g. "First person (I/me)")
            character_context: Detailed POV character info (personality, backstory, etc.)
            scene_description: User's description of the scene context
            surrounding_before: Text immediately before the selection in the document
            surrounding_after: Text immediately after the selection in the document

        Returns:
            RephraseResult with multiple options
        """
        # Normalise: tones list takes priority; fall back to legacy single tone arg
        if tones is None:
            tones = [tone] if tone is not None else [RephraseTone.NEUTRAL]
        if not tones:
            tones = [RephraseTone.NEUTRAL]
        # Keep a single `tone` reference for legacy code paths that still use it
        tone = tones[0]
        custom_tone = custom_tone.strip()

        # Prominent model logging at the start
        print(f"\n{'#'*70}")
        print(f"{'#'*70}")
        print(f"# REPHRASING / GENERAL AI ASSISTANT")
        print(f"{'#'*70}")

        if self.use_python_libraries:
            print(f"🔧 Mode: Python Libraries Only (No AI)")
        elif self.use_local_model:
            model_id = self.local_model_id or "(not set)"
            print(f"🤖 Mode: Local Model")
            print(f"📦 Model: {model_id}")

            # Check if model is cached
            cached_model, _, cached_device = _model_cache.get_model(model_id)
            if cached_model:
                print(f"💾 Cache: [OK] CACHED (instant load)")
                print(f"🖥️  Device: {cached_device.upper()}")
            else:
                print(f"💾 Cache: Not cached (will load - may take 30-120s)")
                try:
                    from src.ai.device_utils import detect_device
                    device_name, _, _ = detect_device()
                    print(f"🖥️  Device: {device_name.upper()}")
                except:
                    print(f"🖥️  Device: Detecting...")
        else:
            print(f"☁️  Mode: Cloud LLM")
            if hasattr(self, '_llm_client') and self._llm_client:
                print(f"📦 Provider: {self._llm_client._provider.value}")

        print(f"📝 Text: {len(text)} chars")
        print(f"🎨 Styles: {len(styles) if styles else 'default'}")
        print(f"🎭 Tones: {[t.value for t in tones]}")
        if custom_tone:
            print(f"✏️  Custom tone: {custom_tone}")
        print(f"{'#'*70}\n")

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

        # Build instructions combining style and tone(s)
        style_instructions = "\n".join([
            f"{i+1}. {self._build_style_tone_instruction(style, tones=tones)} ({style.value})"
            for i, style in enumerate(styles)
        ])

        # Build tone instruction — supports blending preset tones + user's custom tone
        active_tones = [t for t in tones if t != RephraseTone.NEUTRAL]
        tone_descs = [self.TONE_PROMPTS[t] for t in active_tones if self.TONE_PROMPTS.get(t)]
        if custom_tone:
            tone_descs.append(custom_tone)

        tone_note = ""
        if len(tone_descs) == 1:
            tone_note = (
                f"\nEMOTIONAL TONE (this is essential, not optional):\n"
                f"{tone_descs[0]}\n\n"
                f"Every word choice, image, and sentence rhythm must embody this emotion. "
                f"The reader should FEEL it without being told what to feel. "
                f"Do not write 'she felt sad' — write prose that IS sad.\n"
            )
        elif len(tone_descs) > 1:
            tone_block = "\n".join(f"  • {td}" for td in tone_descs)
            tone_note = (
                f"\nEMOTIONAL TONES (blend all of these — this is essential):\n"
                f"{tone_block}\n\n"
                f"Weave these emotions into a single texture. Each variation should feel "
                f"like all these tones exist simultaneously — not switching between them "
                f"but fused into one emotional experience. The reader should FEEL the "
                f"blend in word choice, imagery, rhythm, and connotation.\n"
            )

        # Point of view instruction
        pov = pov.strip() if pov else ""
        pov_note = ""
        if pov:
            pov_note = (
                f"\nRewrite all variations in {pov}. "
                f"Adjust pronouns, verb forms, and perspective accordingly.\n"
            )

        # Character POV context — convert traits into concrete writing directives
        character_context = character_context.strip() if character_context else ""
        char_note = ""
        if character_context:
            voice_rules = _build_character_voice_rules(character_context)
            char_note = (
                f"\nCHARACTER VOICE — this text belongs to a specific character. "
                f"The phrasing must sound like THIS person wrote/thought/said it.\n\n"
                f"CHARACTER PROFILE:\n{character_context}\n\n"
                f"VOICE RULES (follow these strictly):\n{voice_rules}\n"
            )

        # Scene and surrounding text context — helps the model understand what's happening
        scene_note = ""
        scene_description = scene_description.strip() if scene_description else ""
        surrounding_before = surrounding_before.strip() if surrounding_before else ""
        surrounding_after = surrounding_after.strip() if surrounding_after else ""

        if scene_description or surrounding_before or surrounding_after:
            scene_parts = []
            if scene_description:
                scene_parts.append(f"Scene: {scene_description}")
            if surrounding_before or surrounding_after:
                scene_parts.append("Surrounding text from the document (for context only — do NOT rephrase this):")
                if surrounding_before:
                    scene_parts.append(f"[BEFORE]: ...{surrounding_before[-300:]}")
                if surrounding_after:
                    scene_parts.append(f"[AFTER]: {surrounding_after[:300]}...")
            scene_note = (
                "\n" + "\n".join(scene_parts) + "\n"
                "\nIMPORTANT: Only rephrase the original text above. "
                "The surrounding text is provided purely for context — "
                "use it to match flow, tone, and continuity, but do not include it in your output.\n"
            )

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
{context_str}{tone_note}{pov_note}{char_note}{scene_note}
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
            print("[DEBUG] About to call _generate_local()")
            print(f"[DEBUG] Prompt length: {len(prompt)} chars")
            response = self._generate_local(prompt, max_tokens=800)
            print("[DEBUG] _generate_local() returned successfully")
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

        # Pre-clean: skip any remaining prompt echo before the first OPTION marker
        lines = response.split('\n')

        # Find where actual options begin
        start_idx = 0
        prompt_noise = [
            'please rephrase', 'original text:', 'generate these',
            'for each variation', 'format your response',
            'apply a', 'tone to all variations',
        ]
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if not stripped:
                continue
            # Skip lines that look like echoed prompt instructions
            if any(marker in stripped for marker in prompt_noise):
                start_idx = i + 1
                continue
            # Skip numbered instruction lines from prompt (e.g. "1. Clearer and easier...")
            if stripped and stripped[0].isdigit() and '. ' in stripped[:4]:
                style_hints = ['tone', 'easier to understand', 'more detailed', 'poetic and lyrical', 'descriptive with']
                if any(hint in stripped for hint in style_hints):
                    start_idx = i + 1
                    continue
            # Found real content
            break

        if start_idx > 0:
            lines = lines[start_idx:]
            print(f"  [Parse] Skipped {start_idx} prompt-echo lines before parsing")

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
