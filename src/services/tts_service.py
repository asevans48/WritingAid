"""Text-to-Speech service with multiple engine support."""

import asyncio
import tempfile
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Callable
import os


class TTSEngine(Enum):
    """Available TTS engines."""
    SYSTEM = "system"  # pyttsx3 - offline, uses system voices
    EDGE = "edge"  # edge-tts - Microsoft neural voices, requires internet
    VIBEVOICE = "vibevoice"  # VibeVoice Community - high-quality local neural TTS
    CHATTERBOX = "chatterbox"  # Chatterbox Turbo - 350M param high-quality local TTS (MLX)
    KOKORO = "kokoro"  # Kokoro - 82M param high-quality local TTS


@dataclass
class TTSVoice:
    """Represents a TTS voice."""
    id: str
    name: str
    language: str
    gender: str
    engine: TTSEngine
    genres: tuple = ()  # Narrative genres this voice suits (e.g. "horror", "romance")


# ── Narrative genre presets ──────────────────────────────────────
# Maps genre → recommended voice IDs per engine.  The first match
# found in the engine's voice list is selected.

NARRATIVE_GENRES = {
    "horror": {
        "label": "Horror / Dark",
        "description": "Low, measured, tense — dread in every pause",
        "kokoro":     ("am_adam", "bm_george", "am_michael"),
        "edge":       ("en-US-DavisNeural", "en-US-GuyNeural", "en-GB-RyanNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "romance": {
        "label": "Romance",
        "description": "Warm, intimate, expressive — every sigh matters",
        "kokoro":     ("af_heart", "af_bella", "af_nicole"),
        "edge":       ("en-US-AvaMultilingualNeural", "en-US-JennyNeural", "en-US-SaraNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "thriller": {
        "label": "Thriller / Suspense",
        "description": "Crisp, urgent, controlled intensity",
        "kokoro":     ("am_michael", "am_adam", "af_nova"),
        "edge":       ("en-US-BrianMultilingualNeural", "en-US-DavisNeural", "en-US-JasonNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "fantasy": {
        "label": "Fantasy / Epic",
        "description": "Rich, authoritative, grand scope — sweeping narration",
        "kokoro":     ("bm_george", "am_adam", "bf_emma"),
        "edge":       ("en-GB-RyanNeural", "en-US-AndrewMultilingualNeural", "en-GB-SoniaNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "literary": {
        "label": "Literary Fiction",
        "description": "Refined, measured, thoughtful — lets the prose breathe",
        "kokoro":     ("af_sarah", "bf_emma", "bm_george"),
        "edge":       ("en-GB-SoniaNeural", "en-US-EmmaMultilingualNeural", "en-GB-LibbyNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "scifi": {
        "label": "Science Fiction",
        "description": "Clean, precise, slightly detached — future-facing",
        "kokoro":     ("am_michael", "af_nova", "af_sky"),
        "edge":       ("en-US-EmmaMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-JaneNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "mystery": {
        "label": "Mystery / Detective",
        "description": "Steady, observant, measured reveals",
        "kokoro":     ("am_michael", "af_sarah", "am_adam"),
        "edge":       ("en-US-GuyNeural", "en-US-DavisNeural", "en-US-JasonNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "ya": {
        "label": "Young Adult",
        "description": "Energetic, relatable, emotionally present",
        "kokoro":     ("af_nova", "af_bella", "af_sky"),
        "edge":       ("en-US-AriaNeural", "en-GB-MaisieNeural", "en-US-JennyNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "comedy": {
        "label": "Comedy / Humorous",
        "description": "Light, playful, good comic timing",
        "kokoro":     ("af_nova", "af_bella", "am_michael"),
        "edge":       ("en-US-TonyNeural", "en-US-GuyNeural", "en-US-AriaNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "historical": {
        "label": "Historical Fiction",
        "description": "Dignified, period-appropriate gravitas",
        "kokoro":     ("bm_george", "bf_emma", "am_adam"),
        "edge":       ("en-GB-RyanNeural", "en-GB-SoniaNeural", "en-US-AndrewMultilingualNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "childrens": {
        "label": "Children's",
        "description": "Bright, clear, engaging — easy to follow",
        "kokoro":     ("af_sky", "af_bella", "af_nova"),
        "edge":       ("en-GB-MaisieNeural", "en-US-JennyNeural", "en-US-SaraNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
    "nonfiction": {
        "label": "Non-Fiction / Documentary",
        "description": "Authoritative, clear, informative",
        "kokoro":     ("am_michael", "af_sarah", "bm_george"),
        "edge":       ("en-US-AndrewMultilingualNeural", "en-US-JaneNeural", "en-US-DavisNeural"),
        "chatterbox": ("default",),
        "system":     ("default",),
    },
}


def get_genre_voice(genre_key: str, engine_key: str) -> Optional[str]:
    """Return the recommended voice ID for a genre + engine combination."""
    genre = NARRATIVE_GENRES.get(genre_key)
    if not genre:
        return None
    candidates = genre.get(engine_key, ())
    return candidates[0] if candidates else None


def enhance_text_for_speech(text: str, genre_key: str = "") -> str:
    """Use the configured LLM to add natural pauses to text for TTS.

    Adds commas, em-dashes, and ellipses where a human reader would
    breathe or pause for emphasis. Never changes meaning or omits content.
    Returns the original text unchanged if the LLM isn't available.
    """
    if not text or not text.strip():
        return text

    try:
        from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
        from src.config.ai_config import get_ai_config

        ai_config = get_ai_config()
        settings = ai_config.settings

        prefer_local = settings.get("prefer_local_model", False)
        enable_local = settings.get("enable_local_models", False)
        local_model_id = settings.get("local_model_id", "")

        if prefer_local and enable_local and local_model_id:
            is_mlx = "mlx" in local_model_id.lower()
            hf_config = HuggingFaceConfig(
                model_id=local_model_id, use_local=True,
                device=settings.get("local_model_device", "auto"),
                quantization=settings.get("local_model_quantization", "none") if settings.get("local_model_quantization") != "none" else None,
                trust_remote_code=settings.get("local_model_trust_remote_code", False),
            )
            provider = LLMProvider.MLX_LOCAL if is_mlx else LLMProvider.HUGGINGFACE_LOCAL
            llm = LLMClient(provider=provider, hf_config=hf_config)
        else:
            default_provider = settings.get("default_llm", "claude")
            api_key = ai_config.get_api_key(default_provider)
            if not api_key:
                return text
            provider_map = {
                "claude": LLMProvider.CLAUDE,
                "chatgpt": LLMProvider.CHATGPT,
                "openai": LLMProvider.CHATGPT,
                "gemini": LLMProvider.GEMINI,
            }
            provider = provider_map.get(default_provider, LLMProvider.CLAUDE)
            llm = LLMClient(
                provider=provider, api_key=api_key,
                model=ai_config.get_model(default_provider),
            )

        genre_hint = ""
        if genre_key:
            genre_info = NARRATIVE_GENRES.get(genre_key, {})
            if genre_info:
                genre_hint = (
                    f"This is for {genre_info.get('label', genre_key)} narration "
                    f"({genre_info.get('description', '')}). ")

        system = "You reformat text for text-to-speech narration. Output ONLY the reformatted text."
        prompt = (
            f"{genre_hint}Reformat this text so a TTS engine will read it with "
            "natural prosody. Add commas where a narrator would naturally pause "
            "for breath, em-dashes (—) for dramatic pauses, and ellipses (...) "
            "for trailing or suspended thoughts. Expand abbreviations "
            "(Mr. -> Mister, Dr. -> Doctor). Do NOT remove, summarize, reorder, "
            "or add content. Do NOT insert stage directions. Output the "
            "complete reformatted text only.\n\n"
            f"{text}"
        )
        result = llm.generate_text(
            prompt=prompt, system_prompt=system,
            max_tokens=max(len(text) + 200, 2000),
            temperature=0.2)
        return result if result and result.strip() else text
    except Exception as e:
        print(f"[TTS] enhance_text_for_speech failed: {e}")
        return text


class TTSService:
    """Text-to-Speech service supporting multiple engines.

    Provides both offline (pyttsx3) and online (edge-tts) TTS options.
    """

    def __init__(self):
        """Initialize TTS service."""
        self._pyttsx3_engine = None
        self._current_engine = TTSEngine.SYSTEM
        self._is_speaking = False
        self._stop_requested = False
        self._speech_thread: Optional[threading.Thread] = None
        self._macos_say_proc = None  # subprocess.Popen for macOS 'say' command

        # Playback settings
        self._rate = 150  # Words per minute (pyttsx3) - normal speaking pace
        self._volume = 1.0  # 0.0 to 1.0
        self._voice_id: Optional[str] = None

        # Edge-TTS settings
        self._edge_voice = "en-US-AriaNeural"  # Default edge voice

        # VibeVoice settings
        self._vibevoice_model = "1.5B"  # Default model: 0.5B (streaming), 1.5B, 7B
        self._vibevoice_voice = "emma"  # Default voice preset
        self._vibevoice_path: Optional[str] = None  # Installation path

        # Callbacks
        self._on_start: Optional[Callable] = None
        self._on_end: Optional[Callable] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_progress: Optional[Callable[[str], None]] = None  # Progress updates for VibeVoice

        # Initialize pyttsx3 lazily
        self._pyttsx3_available = self._check_pyttsx3()
        self._edge_available = self._check_edge_tts()
        self._vibevoice_available = self._check_vibevoice()

    def _check_pyttsx3(self) -> bool:
        """Check if pyttsx3 is available."""
        try:
            return True
        except ImportError:
            return False

    def _check_edge_tts(self) -> bool:
        """Check if edge-tts is available."""
        try:
            return True
        except ImportError:
            return False

    def _check_vibevoice(self) -> bool:
        """Check if VibeVoice is available."""
        try:
            # Check if vibevoice package is installed
            import importlib.util
            if importlib.util.find_spec("vibevoice") is not None:
                # Find installation path from package
                spec = importlib.util.find_spec("vibevoice")
                if spec and spec.origin:
                    pkg_path = Path(spec.origin).parent.parent
                    if (pkg_path / "demo" / "inference_from_file.py").exists():
                        self._vibevoice_path = str(pkg_path)
                        return True
            # Also check for installation path
            if self._vibevoice_path:
                vv_path = Path(self._vibevoice_path)
                if vv_path.exists() and (vv_path / "demo" / "inference_from_file.py").exists():
                    return True
            # Check common installation paths (cross-platform)
            common_paths = [
                Path.home() / "VibeVoice",
                Path.home() / ".vibevoice",
            ]
            # Add platform-specific paths
            if os.name == 'nt':
                # Windows: check Program Files and root of common drives
                common_paths.extend([
                    Path(os.environ.get('PROGRAMFILES', 'C:\\Program Files')) / "VibeVoice",
                    Path(os.environ.get('LOCALAPPDATA', '')) / "VibeVoice" if os.environ.get('LOCALAPPDATA') else None,
                ])
            else:
                # macOS and Linux
                common_paths.extend([
                    Path("/opt/vibevoice"),
                    Path("/usr/local/vibevoice"),
                    Path.home() / "Applications" / "VibeVoice",  # macOS user Applications
                ])
            # Filter out None values
            common_paths = [p for p in common_paths if p is not None]
            for path in common_paths:
                if path.exists() and (path / "demo" / "inference_from_file.py").exists():
                    self._vibevoice_path = str(path)
                    return True
            return False
        except Exception:
            return False

    def set_vibevoice_path(self, path: str):
        """Set the VibeVoice installation path."""
        self._vibevoice_path = path
        self._vibevoice_available = self._check_vibevoice()

    def get_vibevoice_path(self) -> Optional[str]:
        """Get the VibeVoice installation path."""
        return self._vibevoice_path

    def _init_pyttsx3(self):
        """Initialize pyttsx3 engine (lazy initialization)."""
        if self._pyttsx3_engine is not None:
            return

        try:
            import pyttsx3
            self._pyttsx3_engine = pyttsx3.init()
            self._pyttsx3_engine.setProperty('rate', self._rate)
            self._pyttsx3_engine.setProperty('volume', self._volume)
        except Exception as e:
            print(f"Failed to initialize pyttsx3: {e}")
            self._pyttsx3_available = False

    def get_available_engines(self) -> List[TTSEngine]:
        """Get list of available TTS engines."""
        engines = []
        if self._vibevoice_available:
            engines.append(TTSEngine.VIBEVOICE)  # Preferred when available
        if self._pyttsx3_available:
            engines.append(TTSEngine.SYSTEM)
        if self._edge_available:
            engines.append(TTSEngine.EDGE)
        return engines

    def is_vibevoice_available(self) -> bool:
        """Check if VibeVoice is installed and available."""
        return self._vibevoice_available

    def set_engine(self, engine: TTSEngine):
        """Set the active TTS engine."""
        if engine == TTSEngine.SYSTEM and not self._pyttsx3_available:
            raise ValueError("System TTS (pyttsx3) is not available")
        if engine == TTSEngine.EDGE and not self._edge_available:
            raise ValueError("Edge TTS is not available")
        if engine == TTSEngine.VIBEVOICE and not self._vibevoice_available:
            raise ValueError("VibeVoice is not available. Please install it first.")
        self._current_engine = engine

    def get_voices(self, engine: Optional[TTSEngine] = None) -> List[TTSVoice]:
        """Get available voices for an engine."""
        engine = engine or self._current_engine
        voices = []

        if engine == TTSEngine.SYSTEM:
            voices.extend(self._get_pyttsx3_voices())
        elif engine == TTSEngine.EDGE:
            voices.extend(self._get_edge_voices())
        elif engine == TTSEngine.VIBEVOICE:
            voices.extend(self._get_vibevoice_voices())
        elif engine == TTSEngine.CHATTERBOX:
            voices.extend(self._get_chatterbox_voices())
        elif engine == TTSEngine.KOKORO:
            voices.extend(self._get_kokoro_voices())

        return voices

    def _get_pyttsx3_voices(self) -> List[TTSVoice]:
        """Get system voices.

        On macOS, uses AVSpeechSynthesizer to list ALL installed voices
        including premium/Siri-quality ones downloaded via System Settings.
        Falls back to pyttsx3 on other platforms.
        """
        import platform
        if platform.system() == "Darwin":
            return self._get_macos_voices()

        # Non-macOS: use pyttsx3
        self._init_pyttsx3()
        if not self._pyttsx3_engine:
            return []

        voices = []
        try:
            for voice in self._pyttsx3_engine.getProperty('voices'):
                name = voice.name
                lang = getattr(voice, 'languages', ['en'])[0] if hasattr(voice, 'languages') else 'en'
                if isinstance(lang, bytes):
                    lang = lang.decode('utf-8', errors='ignore')
                gender = "female" if any(f in name.lower() for f in ['zira', 'hazel', 'susan', 'female']) else "male"
                voices.append(TTSVoice(
                    id=voice.id, name=name,
                    language=str(lang)[:5], gender=gender,
                    engine=TTSEngine.SYSTEM
                ))
        except Exception as e:
            print(f"Error getting pyttsx3 voices: {e}")
        return voices

    def _get_macos_voices(self) -> List[TTSVoice]:
        """Get macOS voices via AVSpeechSynthesizer (includes Siri/premium voices).

        Premium voices must be downloaded in:
        System Settings > Accessibility > Spoken Content > System Voice > Manage Voices
        """
        voices = []
        try:
            from AVFoundation import AVSpeechSynthesisVoice

            quality_labels = {1: "", 2: " [Enhanced]", 3: " [Premium]"}
            # Novelty/joke voices to sort to the end
            novelty = {'albert', 'bad news', 'bahh', 'bells', 'boing',
                       'bubbles', 'cellos', 'good news', 'jester', 'junior',
                       'kathy', 'organ', 'superstar', 'ralph', 'trinoids',
                       'whisper', 'zarvox', 'wobble'}

            # Language region labels for display
            region_labels = {
                'en-US': 'US', 'en-GB': 'UK', 'en-AU': 'AU',
                'en-IE': 'IE', 'en-IN': 'IN', 'en-ZA': 'ZA',
                'en-CA': 'CA', 'en-NZ': 'NZ',
            }

            female_names = {'samantha', 'karen', 'moira', 'flo', 'sandy',
                            'shelley', 'grandma', 'ava', 'allison', 'susan',
                            'kate', 'tessa', 'veena', 'victoria', 'zoe',
                            'siri', 'alice', 'amelie', 'anna', 'sara',
                            'nora', 'tina', 'kathy'}

            for v in AVSpeechSynthesisVoice.speechVoices():
                name = str(v.name())
                lang = str(v.language())
                ident = str(v.identifier())
                quality = v.quality()  # 1=default, 2=enhanced, 3=premium
                q_suffix = quality_labels.get(quality, "")

                # Only show English voices (this is a writing app)
                if not lang.startswith('en'):
                    continue

                base_name = name.split('(')[0].strip().lower()
                gender = "female" if base_name in female_names else "male"
                is_novelty = base_name in novelty

                # Identify Siri natural voices (the "Voice 1-4" slots in
                # macOS System Settings > Accessibility > Spoken Content).
                # Quality >= 2 is the definitive marker (Enhanced or Premium).
                # Identifier patterns catch cases where quality flag isn't set.
                is_siri = (quality >= 2 or
                           'siri' in ident.lower() or
                           'natural' in ident.lower() or
                           'premium' in ident.lower() or
                           'enhanced' in ident.lower())

                region = region_labels.get(lang, lang)
                if is_siri:
                    # Highlight Siri voices with a clear prefix
                    display = f"🎙 Siri: {name} ({region}){q_suffix}"
                elif '(' in name:
                    display = f"{name}{q_suffix}"
                else:
                    display = f"{name} ({region}){q_suffix}"

                # Sort key: Siri voices first (0), then by -quality,
                # then novelty last
                sort_rank = 0 if is_siri else (2 if is_novelty else 1)
                voices.append((sort_rank, -quality, display, TTSVoice(
                    id=ident, name=display,
                    language=lang, gender=gender,
                    engine=TTSEngine.SYSTEM
                )))

            voices.sort(key=lambda x: (x[0], x[1], x[2]))

            # Add "System Default" at the very top — uses whatever macOS has set
            result = [TTSVoice(
                id="default", name="⭐ System Default (macOS Spoken Content)",
                language="en", gender="neutral",
                engine=TTSEngine.SYSTEM
            )]
            result.extend(v[3] for v in voices)
            return result

        except ImportError:
            print("[TTS] AVFoundation not available — falling back to pyttsx3")
            # Fallback to pyttsx3 if pyobjc/AVFoundation isn't installed
            self._init_pyttsx3()
            if not self._pyttsx3_engine:
                return []
            result = []
            try:
                for voice in self._pyttsx3_engine.getProperty('voices'):
                    name = voice.name
                    lang = getattr(voice, 'languages', ['en'])[0] if hasattr(voice, 'languages') else 'en'
                    if isinstance(lang, bytes):
                        lang = lang.decode('utf-8', errors='ignore')
                    result.append(TTSVoice(
                        id=voice.id, name=name,
                        language=str(lang)[:5], gender="male",
                        engine=TTSEngine.SYSTEM
                    ))
            except Exception as e:
                print(f"Error getting pyttsx3 voices: {e}")
            return result
        except Exception as e:
            print(f"Error getting macOS voices: {e}")
            return []

    def _get_edge_voices(self) -> List[TTSVoice]:
        """Get edge-tts voices curated for narration and storytelling."""
        # Curated list of the best Microsoft Edge neural voices for reading prose.
        # Multilingual voices marked with (Multilingual) can switch styles/languages.
        # Voices are sorted by quality for long-form narration.
        voices = [
            # --- Top picks for narration (US) ---
            TTSVoice("en-US-AvaMultilingualNeural", "Ava (US, Multilingual) - warm narrator", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-US-AndrewMultilingualNeural", "Andrew (US, Multilingual) - calm narrator", "en-US", "male", TTSEngine.EDGE),
            TTSVoice("en-US-EmmaMultilingualNeural", "Emma (US, Multilingual) - clear narrator", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-US-BrianMultilingualNeural", "Brian (US, Multilingual) - deep narrator", "en-US", "male", TTSEngine.EDGE),
            TTSVoice("en-US-AriaNeural", "Aria (US) - expressive", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-US-JennyNeural", "Jenny (US) - friendly", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-US-GuyNeural", "Guy (US) - conversational", "en-US", "male", TTSEngine.EDGE),
            TTSVoice("en-US-DavisNeural", "Davis (US) - authoritative", "en-US", "male", TTSEngine.EDGE),
            TTSVoice("en-US-JaneNeural", "Jane (US) - professional", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-US-JasonNeural", "Jason (US) - steady", "en-US", "male", TTSEngine.EDGE),
            TTSVoice("en-US-NancyNeural", "Nancy (US) - warm", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-US-TonyNeural", "Tony (US) - engaging", "en-US", "male", TTSEngine.EDGE),
            TTSVoice("en-US-SaraNeural", "Sara (US) - gentle", "en-US", "female", TTSEngine.EDGE),
            # --- British voices (great for literary prose) ---
            TTSVoice("en-GB-SoniaNeural", "Sonia (UK) - refined", "en-GB", "female", TTSEngine.EDGE),
            TTSVoice("en-GB-RyanNeural", "Ryan (UK) - articulate", "en-GB", "male", TTSEngine.EDGE),
            TTSVoice("en-GB-LibbyNeural", "Libby (UK) - natural", "en-GB", "female", TTSEngine.EDGE),
            TTSVoice("en-GB-MaisieNeural", "Maisie (UK) - young", "en-GB", "female", TTSEngine.EDGE),
            # --- Other English variants ---
            TTSVoice("en-AU-NatashaNeural", "Natasha (AU)", "en-AU", "female", TTSEngine.EDGE),
            TTSVoice("en-AU-WilliamNeural", "William (AU)", "en-AU", "male", TTSEngine.EDGE),
            TTSVoice("en-CA-ClaraNeural", "Clara (CA)", "en-CA", "female", TTSEngine.EDGE),
            TTSVoice("en-CA-LiamNeural", "Liam (CA)", "en-CA", "male", TTSEngine.EDGE),
            TTSVoice("en-IE-EmilyNeural", "Emily (IE)", "en-IE", "female", TTSEngine.EDGE),
            TTSVoice("en-IE-ConnorNeural", "Connor (IE)", "en-IE", "male", TTSEngine.EDGE),
            TTSVoice("en-IN-NeerjaNeural", "Neerja (IN)", "en-IN", "female", TTSEngine.EDGE),
        ]
        return voices

    def _get_vibevoice_voices(self) -> List[TTSVoice]:
        """Get VibeVoice voice presets."""
        # VibeVoice Community voice presets
        voices = [
            TTSVoice("carter", "Carter", "en-US", "male", TTSEngine.VIBEVOICE),
            TTSVoice("davis", "Davis", "en-US", "male", TTSEngine.VIBEVOICE),
            TTSVoice("emma", "Emma", "en-US", "female", TTSEngine.VIBEVOICE),
            TTSVoice("frank", "Frank", "en-US", "male", TTSEngine.VIBEVOICE),
            TTSVoice("grace", "Grace", "en-US", "female", TTSEngine.VIBEVOICE),
            TTSVoice("mike", "Mike", "en-US", "male", TTSEngine.VIBEVOICE),
            TTSVoice("samuel", "Samuel", "en-US", "male", TTSEngine.VIBEVOICE),
        ]
        return voices

    def _get_chatterbox_voices(self) -> List[TTSVoice]:
        """Get Chatterbox Turbo voices (default + any reference audio in ~/.writer_platform/voices/)."""
        voices = [
            TTSVoice("default", "Default (Neural)", "en", "neutral", TTSEngine.CHATTERBOX),
        ]
        # Scan for user-provided reference audio files for voice cloning
        voices_dir = Path.home() / ".writer_platform" / "voices"
        if voices_dir.exists():
            for f in sorted(voices_dir.iterdir()):
                if f.suffix.lower() in ('.wav', '.mp3', '.flac', '.ogg'):
                    name = f.stem.replace('_', ' ').replace('-', ' ').title()
                    voices.append(TTSVoice(
                        str(f), f"{name} (cloned)", "en", "neutral",
                        TTSEngine.CHATTERBOX))
        return voices

    def _get_kokoro_voices(self) -> List[TTSVoice]:
        """Get Kokoro voice presets with narrative genre tags."""
        voices = [
            TTSVoice("af_heart", "Heart (warm, natural)", "en-US", "female", TTSEngine.KOKORO,
                     genres=("romance",)),
            TTSVoice("af_bella", "Bella (clear, bright)", "en-US", "female", TTSEngine.KOKORO,
                     genres=("romance", "ya", "comedy")),
            TTSVoice("af_sarah", "Sarah (calm, steady)", "en-US", "female", TTSEngine.KOKORO,
                     genres=("literary", "mystery", "nonfiction")),
            TTSVoice("af_nicole", "Nicole (smooth)", "en-US", "female", TTSEngine.KOKORO,
                     genres=("romance", "literary")),
            TTSVoice("af_sky", "Sky (light, airy)", "en-US", "female", TTSEngine.KOKORO,
                     genres=("ya", "childrens", "scifi")),
            TTSVoice("af_nova", "Nova (energetic)", "en-US", "female", TTSEngine.KOKORO,
                     genres=("ya", "comedy", "scifi", "thriller")),
            TTSVoice("am_adam", "Adam (deep, warm)", "en-US", "male", TTSEngine.KOKORO,
                     genres=("horror", "fantasy", "thriller", "historical")),
            TTSVoice("am_michael", "Michael (clear)", "en-US", "male", TTSEngine.KOKORO,
                     genres=("thriller", "mystery", "scifi", "nonfiction")),
            TTSVoice("bf_emma", "Emma (British)", "en-GB", "female", TTSEngine.KOKORO,
                     genres=("literary", "historical", "fantasy")),
            TTSVoice("bm_george", "George (British)", "en-GB", "male", TTSEngine.KOKORO,
                     genres=("fantasy", "historical", "literary", "horror")),
        ]
        return voices

    def get_vibevoice_models(self) -> List[str]:
        """Get available VibeVoice models."""
        return ["0.5B", "1.5B", "7B"]

    def set_vibevoice_model(self, model: str):
        """Set the VibeVoice model to use."""
        if model in self.get_vibevoice_models():
            self._vibevoice_model = model

    def set_vibevoice_voice(self, voice: str):
        """Set the VibeVoice voice preset."""
        self._vibevoice_voice = voice

    def set_voice(self, voice_id: str):
        """Set the voice to use."""
        self._voice_id = voice_id
        if self._current_engine == TTSEngine.EDGE:
            self._edge_voice = voice_id
        elif self._current_engine == TTSEngine.VIBEVOICE:
            self._vibevoice_voice = voice_id
        elif self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.setProperty('voice', voice_id)
            except Exception as e:
                print(f"Error setting voice: {e}")

    def set_rate(self, rate: int):
        """Set speech rate (words per minute for pyttsx3, percentage for edge)."""
        self._rate = rate
        if self._pyttsx3_engine:
            self._pyttsx3_engine.setProperty('rate', rate)

    def set_volume(self, volume: float):
        """Set volume (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, volume))
        if self._pyttsx3_engine:
            self._pyttsx3_engine.setProperty('volume', self._volume)

    def set_callbacks(
        self,
        on_start: Optional[Callable] = None,
        on_end: Optional[Callable] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None
    ):
        """Set callback functions for speech events.

        Args:
            on_start: Called when speech starts
            on_end: Called when speech ends
            on_error: Called on error with error message
            on_progress: Called with progress updates (mainly for VibeVoice)
        """
        self._on_start = on_start
        self._on_end = on_end
        self._on_error = on_error
        self._on_progress = on_progress

    @property
    def is_speaking(self) -> bool:
        """Check if currently speaking."""
        return self._is_speaking

    @property
    def is_paused(self) -> bool:
        """Check if playback is currently paused."""
        return getattr(self, '_is_paused', False)

    def pause(self):
        """Pause the current speech (can be resumed with resume())."""
        # AVSpeechSynthesizer path (macOS Siri voices)
        av_synth = getattr(self, '_avspeech_synth', None)
        if av_synth is not None:
            try:
                # AVSpeechBoundaryImmediate = 0
                av_synth.pauseSpeakingAtBoundary_(0)
                self._is_paused = True
                return True
            except Exception as e:
                print(f"[TTS] pause via AVSpeech failed: {e}")

        # afplay subprocess path (macOS fallback)
        proc = getattr(self, '_macos_say_proc', None) or getattr(self, '_audio_proc', None)
        if proc is not None and proc.poll() is None:
            try:
                import signal
                proc.send_signal(signal.SIGSTOP)
                self._is_paused = True
                return True
            except Exception as e:
                print(f"[TTS] pause via SIGSTOP failed: {e}")

        return False

    def resume(self):
        """Resume playback after pause()."""
        av_synth = getattr(self, '_avspeech_synth', None)
        if av_synth is not None:
            try:
                av_synth.continueSpeaking()
                self._is_paused = False
                return True
            except Exception as e:
                print(f"[TTS] resume via AVSpeech failed: {e}")

        proc = getattr(self, '_macos_say_proc', None) or getattr(self, '_audio_proc', None)
        if proc is not None and proc.poll() is None:
            try:
                import signal
                proc.send_signal(signal.SIGCONT)
                self._is_paused = False
                return True
            except Exception as e:
                print(f"[TTS] resume via SIGCONT failed: {e}")

        return False

    def speak(self, text: str):
        """Speak text using the current engine (non-blocking)."""
        # Always reset state first - this ensures we can start fresh
        self._stop_requested = False
        self._is_paused = False

        # If still marked as speaking, force reset
        if self._is_speaking:
            self.stop()
            # Wait briefly for previous speech to stop
            import time
            time.sleep(0.1)
            # Force reset in case stop didn't fully complete
            self._is_speaking = False
            self._stop_requested = False

        self._is_speaking = True

        voice_name = self._voice_id or "default"
        print(f"[TTS] Read Aloud: engine={self._current_engine.value}, "
              f"voice={voice_name}, text={len(text)} chars")

        if self._on_start:
            self._on_start()

        if self._current_engine == TTSEngine.SYSTEM:
            self._speech_thread = threading.Thread(
                target=self._speak_pyttsx3,
                args=(text,),
                daemon=True
            )
        elif self._current_engine == TTSEngine.VIBEVOICE:
            self._speech_thread = threading.Thread(
                target=self._speak_vibevoice,
                args=(text,),
                daemon=True
            )
        elif self._current_engine == TTSEngine.CHATTERBOX:
            self._speech_thread = threading.Thread(
                target=self._speak_chatterbox,
                args=(text,),
                daemon=True
            )
        elif self._current_engine == TTSEngine.KOKORO:
            self._speech_thread = threading.Thread(
                target=self._speak_kokoro,
                args=(text,),
                daemon=True
            )
        else:
            self._speech_thread = threading.Thread(
                target=self._speak_edge,
                args=(text,),
                daemon=True
            )

        self._speech_thread.start()

    def _speak_pyttsx3(self, text: str):
        """Speak using pyttsx3 (runs in thread).

        On macOS, pyttsx3's runAndWait() has a known issue where it returns
        before the OS audio system finishes playing the queued speech. We use
        the macOS built-in 'say' command via subprocess instead, which blocks
        reliably until audio is done.
        """
        try:
            import platform
            if platform.system() == "Darwin":
                self._speak_macos_say(text)
                return

            self._init_pyttsx3()
            if not self._pyttsx3_engine:
                raise RuntimeError("pyttsx3 not initialized")

            # Set voice if specified
            if self._voice_id:
                self._pyttsx3_engine.setProperty('voice', self._voice_id)

            self._pyttsx3_engine.say(text)
            self._pyttsx3_engine.runAndWait()

        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
        finally:
            self._is_speaking = False
            if self._on_end:
                self._on_end()

    def _find_default_macos_voice_id(self) -> Optional[str]:
        """Return the identifier of the user's configured macOS system voice.

        Reads com.apple.accessibility SpokenContentDefaultVoiceSelectionsByLanguage
        to find the exact voice ID the user selected in System Settings.
        Returns None if not configured or on error.
        """
        try:
            import subprocess
            result = subprocess.run(
                ['defaults', 'read', 'com.apple.accessibility',
                 'SpokenContentDefaultVoiceSelectionsByLanguage'],
                capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                import re
                m = re.search(r'voiceId\s*=\s*"([^"]+)"', result.stdout)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None

    def _find_default_macos_voice(self) -> str:
        """Resolve system default to a voice NAME (for `say -v` fallback).

        Tries the user's configured Spoken Content voice first, falls back
        to a heuristic preferring Siri natural voices, then Samantha.
        """
        preferred_voice_id = self._find_default_macos_voice_id()

        try:
            from AVFoundation import AVSpeechSynthesisVoice
            all_voices = list(AVSpeechSynthesisVoice.speechVoices())

            if preferred_voice_id:
                for v in all_voices:
                    if str(v.identifier()) == preferred_voice_id:
                        return str(v.name()).split('(')[0].strip()

            en_voices = [v for v in all_voices
                         if str(v.language()).startswith('en')]
            if not en_voices:
                return "Samantha"

            def rank(v):
                ident = str(v.identifier()).lower()
                is_siri = ('siri' in ident or 'natural' in ident or
                           'premium' in ident)
                return (0 if is_siri else 1, -v.quality())

            en_voices.sort(key=rank)

            novelty = {'albert', 'bad news', 'bahh', 'bells', 'boing',
                       'bubbles', 'cellos', 'good news', 'jester', 'junior',
                       'organ', 'superstar', 'ralph', 'trinoids',
                       'whisper', 'zarvox', 'wobble', 'kathy'}
            for v in en_voices:
                name = str(v.name()).split('(')[0].strip()
                if name.lower() not in novelty:
                    return name
            return str(en_voices[0].name()).split('(')[0].strip()
        except Exception:
            return "Samantha"

    def _speak_macos_say(self, text: str):
        """Speak on macOS using AVSpeechSynthesizer.

        The `say` command-line tool cannot access Siri/premium natural
        voices — they're only available through AVSpeechSynthesizer.  To
        support those voices we dispatch the synthesis to the main thread
        (which has a pumping run loop in Qt apps) and wait for completion.

        Falls back to `say -v <name>` if pyobjc isn't available.
        """
        # Try AVSpeechSynthesizer first (required for Siri voices)
        if self._speak_macos_avspeech(text):
            return
        # Fall back to say command for basic voices
        self._speak_macos_say_cmd(text)

    def _speak_macos_avspeech(self, text: str) -> bool:
        """Speak via AVSpeechSynthesizer on the main thread.

        Returns True if audio played successfully, False if pyobjc/AVFoundation
        is unavailable so the caller should fall back to `say`.
        """
        try:
            from AVFoundation import (
                AVSpeechSynthesisVoice, AVSpeechSynthesizer, AVSpeechUtterance,
            )
            from Foundation import NSObject, NSRunLoop, NSDate, NSThread
            import objc as _objc
            import threading as _threading
            import time as _t
        except ImportError:
            return False

        # Resolve voice — user's explicit choice first, then macOS system
        # default (read from com.apple.accessibility plist as a voice ID),
        # then heuristic fallback.
        voice = None
        voice_label = "default"

        # Cache the full voice list once; also use it for manual lookup in
        # case voiceWithIdentifier_ returns None due to pyobjc quirks.
        all_voices = list(AVSpeechSynthesisVoice.speechVoices())

        # One-time: log all enhanced/premium/Siri voices to help diagnose
        # voice-resolution issues
        if not getattr(self, '_logged_voices', False):
            self._logged_voices = True
            siri_list = []
            for v in all_voices:
                q = v.quality()
                ident = str(v.identifier()).lower()
                if q >= 2 or 'siri' in ident or 'natural' in ident or 'premium' in ident:
                    siri_list.append(v)
            if siri_list:
                print(f"[TTS/AVSpeech] Installed Siri/Premium voices ({len(siri_list)}):")
                for v in sorted(siri_list, key=lambda x: (-x.quality(), str(x.name()))):
                    print(f"  q={v.quality()} lang={v.language()} "
                          f"name={str(v.name())!r} id={str(v.identifier())!r}")
            else:
                print(f"[TTS/AVSpeech] No Siri/Premium voices detected. "
                      f"Total voices: {len(all_voices)}")

        def find_by_id(target_id):
            # Try the official lookup first
            v = AVSpeechSynthesisVoice.voiceWithIdentifier_(target_id)
            if v:
                return v
            # Fall back to linear scan with string comparison
            for v in all_voices:
                if str(v.identifier()) == str(target_id):
                    return v
            return None

        if self._voice_id and self._voice_id != "default":
            # User explicitly picked a voice — use its exact identifier
            voice = find_by_id(self._voice_id)
            if voice:
                voice_label = str(voice.name())
            else:
                print(f"[TTS/AVSpeech] Voice id {self._voice_id!r} not found.")
                print(f"[TTS/AVSpeech] Installed Siri/premium English voices:")
                for v in all_voices:
                    ident = str(v.identifier()).lower()
                    if str(v.language()).startswith('en') and (
                            'siri' in ident or 'natural' in ident or v.quality() >= 2):
                        print(f"  {v.name()!r} q={v.quality()} "
                              f"id={str(v.identifier())!r}")

        if voice is None:
            # Use the user's macOS Spoken Content voice — via exact identifier
            preferred_id = self._find_default_macos_voice_id()
            if preferred_id:
                voice = find_by_id(preferred_id)
                if voice:
                    voice_label = f"{voice.name()} (Spoken Content default)"
                    print(f"[TTS/AVSpeech] Resolved macOS Spoken Content default: "
                          f"id={preferred_id!r}")
                else:
                    print(f"[TTS/AVSpeech] Spoken Content voice {preferred_id!r} "
                          f"not found in AVSpeechSynthesizer — scanning for "
                          f"installed Siri voices")

        if voice is None:
            # Try to find any installed Siri natural voice (the 4 Apple
            # voices downloaded via System Settings > Spoken Content).
            # Quality >= 2 = Enhanced/Premium. Also check id patterns.
            siri_voices = []
            for v in all_voices:
                ident = str(v.identifier()).lower()
                if not str(v.language()).startswith('en'):
                    continue
                if (v.quality() >= 2 or 'siri' in ident or 'natural' in ident
                        or 'premium' in ident or 'enhanced' in ident):
                    siri_voices.append(v)
            if siri_voices:
                siri_voices.sort(key=lambda v: -v.quality())
                voice = siri_voices[0]
                voice_label = (f"{voice.name()} (Siri voice, "
                               f"q={voice.quality()})")
                print(f"[TTS/AVSpeech] Using installed Siri voice: "
                      f"id={str(voice.identifier())!r}")

        if voice is None:
            # Last resort: heuristic — any high-quality English voice
            default_name = self._find_default_macos_voice()
            best = None
            for v in all_voices:
                n = str(v.name()).split('(')[0].strip()
                if n == default_name and str(v.language()).startswith('en'):
                    if best is None or v.quality() > best.quality():
                        best = v
            if best:
                voice = best
                voice_label = f"{default_name} (heuristic fallback, q={best.quality()})"
                # If the user's Spoken Content setting points to a Siri voice
                # that isn't downloaded, call it out clearly
                preferred_id = self._find_default_macos_voice_id()
                if preferred_id and ('siri' in preferred_id.lower() or
                                      'natural' in preferred_id.lower() or
                                      'premium' in preferred_id.lower()):
                    print(f"[TTS/AVSpeech] ⚠️  Your macOS Spoken Content is set to "
                          f"{preferred_id!r} but that voice is NOT downloaded.")
                    print(f"[TTS/AVSpeech] To install it: System Settings > "
                          f"Accessibility > Spoken Content > System Voice > "
                          f"Manage Voices... > click the download arrow next to "
                          f"your Siri voice (Voice 1-4).")
                    print(f"[TTS/AVSpeech] Using basic {default_name} instead.")
                else:
                    print(f"[TTS/AVSpeech] No Siri voices installed — using basic {default_name}")

        if voice is None:
            print("[TTS/AVSpeech] ERROR: no voice found, falling back to say")
            return False

        print(f"[TTS/AVSpeech] Voice: {voice_label} "
              f"id={str(voice.identifier())!r} q={voice.quality()}, "
              f"text={len(text)} chars")

        # Build utterance
        utt = AVSpeechUtterance.speechUtteranceWithString_(text)
        utt.setVoice_(voice)
        if self._rate:
            av_rate = max(0.1, min(1.0, (self._rate / 150.0) * 0.5))
            utt.setRate_(av_rate)
        utt.setVolume_(self._volume)

        done_event = _threading.Event()
        synth_ref = [None]
        error_ref = [None]

        # Dispatch synthesis to the main thread (where Qt's run loop is pumping
        # on macOS, which handles AVSpeechSynthesizer callbacks).
        class _SpeechRunner(NSObject):
            def run_(self_, utt_obj):
                try:
                    synth = AVSpeechSynthesizer.alloc().init()
                    synth_ref[0] = synth
                    synth.speakUtterance_(utt_obj)
                except Exception as e:
                    error_ref[0] = str(e)
                    done_event.set()

        runner = _SpeechRunner.alloc().init()
        runner.performSelectorOnMainThread_withObject_waitUntilDone_(
            'run:', utt, False)

        # Wait for synthesis to start, with a timeout
        _t0 = _t.time()
        while synth_ref[0] is None and _t.time() - _t0 < 5:
            _t.sleep(0.05)

        if synth_ref[0] is None:
            print(f"[TTS/AVSpeech] ERROR: synth never started. err={error_ref[0]}")
            return False

        # Store synth so stop() can cancel it
        self._avspeech_synth = synth_ref[0]

        # Poll until speech completes or stop is requested
        play_start = _t.time()
        while synth_ref[0].isSpeaking() or synth_ref[0].isPaused():
            _t.sleep(0.1)
            if self._stop_requested:
                synth_ref[0].stopSpeakingAtBoundary_(0)  # AVSpeechBoundaryImmediate
                break
            if _t.time() - play_start > 600:
                print("[TTS/AVSpeech] Timeout after 10 minutes")
                synth_ref[0].stopSpeakingAtBoundary_(0)
                break

        self._avspeech_synth = None
        duration = _t.time() - play_start
        print(f"[TTS/AVSpeech] Playback complete in {duration:.2f}s")
        return True

    def _speak_macos_say_cmd(self, text: str):
        """Fallback: speak using `say -o` + `afplay` (basic voices only).

        - `say -o` requires `-v <name>` or it produces an empty file
        - Cannot access Siri/premium voices
        """
        import subprocess
        import time as _t
        import tempfile as _tf

        if not text.strip():
            print("[TTS/say] ERROR: empty text — aborting")
            return

        # Resolve voice name from voice ID using AVSpeechSynthesizer
        voice_name = None
        voice_quality = 1
        resolved_identifier = None

        if self._voice_id and self._voice_id != "default":
            try:
                from AVFoundation import AVSpeechSynthesisVoice
                for v in AVSpeechSynthesisVoice.speechVoices():
                    if str(v.identifier()) == self._voice_id:
                        voice_name = str(v.name()).split('(')[0].strip()
                        voice_quality = v.quality()
                        resolved_identifier = self._voice_id
                        break
            except Exception:
                pass

        if not voice_name:
            voice_name = self._find_default_macos_voice()
            try:
                from AVFoundation import AVSpeechSynthesisVoice
                for v in AVSpeechSynthesisVoice.speechVoices():
                    n = str(v.name()).split('(')[0].strip()
                    if n == voice_name:
                        voice_quality = v.quality()
                        resolved_identifier = str(v.identifier())
                        break
            except Exception:
                pass

        # Write text to a temp file
        with _tf.NamedTemporaryFile(
                mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(text)
            text_file = f.name

        audio_file = text_file.replace('.txt', '.aiff')

        # For high-quality (Siri/Premium) voices where the short name might
        # match a basic voice too, try the full identifier first — some
        # macOS versions accept it for -v.
        quality_labels = {1: "default", 2: "enhanced", 3: "premium"}
        print(f"[TTS/say] Voice: {voice_name} "
              f"(quality={quality_labels.get(voice_quality, 'unknown')}, "
              f"id={resolved_identifier}), text={len(text)} chars")

        rate_args = ['-r', str(int(self._rate))] if self._rate else []

        # Try using the full identifier first for enhanced/premium voices
        # (some macOS versions accept it); fall back to the short name
        def try_generate(voice_spec):
            cmd = ['say', '-v', voice_spec] + rate_args + [
                '-o', audio_file, '-f', text_file]
            result = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=120)
            import os as _os
            size = _os.path.getsize(audio_file) if _os.path.exists(audio_file) else 0
            return result.returncode == 0 and size > 5000, size, result.stderr

        try:
            gen_start = _t.time()
            success = False
            file_size = 0

            # For enhanced/premium voices, try full identifier first
            if voice_quality > 1 and resolved_identifier:
                success, file_size, stderr = try_generate(resolved_identifier)
                if success:
                    print(f"[TTS/say] Used full identifier for {voice_quality}-quality voice")

            # Fall back to short name
            if not success:
                success, file_size, stderr = try_generate(voice_name)

            gen_duration = _t.time() - gen_start
            print(f"[TTS/say] Generated {file_size} bytes in {gen_duration:.2f}s")

            if not success or file_size < 1000:
                err_msg = stderr.decode(errors='replace') if stderr else ''
                print(f"[TTS/say] ERROR: audio too small ({file_size} bytes). "
                      f"stderr: {err_msg}")
                return

            if self._stop_requested:
                return

            # Play with afplay
            play_start = _t.time()
            play_proc = subprocess.Popen(
                ['afplay', audio_file],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._macos_say_proc = play_proc

            while True:
                try:
                    play_proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if self._stop_requested:
                        play_proc.terminate()
                        try:
                            play_proc.wait(timeout=1.0)
                        except subprocess.TimeoutExpired:
                            play_proc.kill()
                        break

            play_duration = _t.time() - play_start
            expected_play = max(1.0, len(text) / 20)
            if play_duration < expected_play and not self._stop_requested:
                print(f"[TTS/say] WARNING: afplay exited in {play_duration:.2f}s "
                      f"(expected ~{expected_play:.1f}s). Check audio output.")
            else:
                print(f"[TTS/say] Playback complete in {play_duration:.2f}s")

        except subprocess.TimeoutExpired:
            print(f"[TTS/say] Generation timed out")
        except Exception as e:
            print(f"[TTS/say] Error: {e}")
        finally:
            self._macos_say_proc = None
            for f in (text_file, audio_file):
                try:
                    os.unlink(f)
                except Exception:
                    pass

    def _speak_edge(self, text: str):
        """Speak using edge-tts (runs in thread)."""
        try:
            import edge_tts

            # Create temporary file for audio
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                temp_path = f.name

            # Generate speech
            async def generate():
                communicate = edge_tts.Communicate(text, self._edge_voice)
                await communicate.save(temp_path)

            asyncio.run(generate())

            if self._stop_requested:
                return

            # Play the audio
            self._play_audio_file(temp_path)

            # Cleanup
            try:
                os.unlink(temp_path)
            except:
                pass

        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
        finally:
            self._is_speaking = False
            if self._on_end:
                self._on_end()

    def _speak_vibevoice(self, text: str):
        """Speak using VibeVoice (runs in thread)."""
        try:
            import subprocess
            import sys

            def report_progress(msg: str):
                if self._on_progress:
                    self._on_progress(msg)

            report_progress("Preparing text for VibeVoice...")

            # Create temporary file for audio output
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                temp_path = f.name

            # Prepare the VibeVoice command
            vibevoice_path = self._vibevoice_path or str(Path.home() / "VibeVoice")

            # Create a temporary text file for input
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as txt_file:
                txt_file.write(text)
                text_path = txt_file.name

            # Build the inference command
            script_path = Path(vibevoice_path) / "demo" / "inference_from_file.py"

            # Map model size to checkpoint
            model_map = {
                "0.5B": "VibeVoice-0.5B",
                "1.5B": "VibeVoice-1.5B",
                "7B": "VibeVoice-7B"
            }
            model_name = model_map.get(self._vibevoice_model, "VibeVoice-1.5B")

            report_progress(f"Loading VibeVoice model ({self._vibevoice_model})...")

            cmd = [
                sys.executable,
                str(script_path),
                "--model_path", f"vibevoice/{model_name}",
                "--txt_path", text_path,
                "--speaker_names", self._vibevoice_voice.capitalize(),
                "--output_path", temp_path,
            ]

            report_progress("Generating speech with VibeVoice...")

            # Run VibeVoice with Popen for real-time output monitoring
            process = subprocess.Popen(
                cmd,
                cwd=vibevoice_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Monitor output for progress indicators
            stdout_lines = []
            stderr_lines = []

            while True:
                if self._stop_requested:
                    process.terminate()
                    return

                # Check if process has completed
                retcode = process.poll()

                # Read any available output
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        stdout_lines.append(line)
                        # Look for progress indicators in output
                        line_lower = line.lower()
                        if "loading" in line_lower:
                            report_progress("Loading model weights...")
                        elif "processing" in line_lower or "generating" in line_lower:
                            report_progress("Generating audio...")
                        elif "saving" in line_lower or "writing" in line_lower:
                            report_progress("Saving audio file...")

                if retcode is not None:
                    # Process completed, read remaining output
                    remaining_stdout, remaining_stderr = process.communicate()
                    stdout_lines.append(remaining_stdout)
                    stderr_lines.append(remaining_stderr)
                    break

            # Clean up text file
            try:
                os.unlink(text_path)
            except:
                pass

            if process.returncode != 0:
                stderr_text = ''.join(stderr_lines)
                raise RuntimeError(f"VibeVoice error: {stderr_text}")

            if self._stop_requested:
                return

            report_progress("Playing audio...")

            # Play the audio
            self._play_audio_file(temp_path)

            # Cleanup
            try:
                os.unlink(temp_path)
            except:
                pass

        except subprocess.TimeoutExpired:
            if self._on_error:
                self._on_error("VibeVoice timed out generating speech")
        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
        finally:
            self._is_speaking = False
            if self._on_end:
                self._on_end()

    def _speak_chatterbox(self, text: str):
        """Speak using Chatterbox Turbo via mlx-audio (runs in thread).

        Downloads the model from HuggingFace on first use (~3 GB).
        Supports voice cloning from a reference audio file.
        """
        try:
            if self._on_progress:
                self._on_progress("Loading Chatterbox Turbo...")

            if not hasattr(self, '_chatterbox_model') or self._chatterbox_model is None:
                print("[TTS] Loading Chatterbox Turbo model (will download on first use)...")
                from mlx_audio.tts.utils import load_model
                self._chatterbox_model = load_model(
                    "mlx-community/chatterbox-turbo-fp16")
                print("[TTS] Chatterbox Turbo loaded")

            if self._stop_requested:
                return

            if self._on_progress:
                self._on_progress("Generating speech...")

            # Check if voice is a file path (cloned voice) or "default"
            voice_id = getattr(self, '_current_voice', 'default')
            gen_kwargs = {"text": text, "stream": False}
            if voice_id and voice_id != "default" and os.path.isfile(voice_id):
                gen_kwargs["ref_audio"] = voice_id

            results = list(self._chatterbox_model.generate(**gen_kwargs))

            if self._stop_requested or not results:
                return

            # Save to temp file and play
            import soundfile as sf
            import numpy as np
            temp_path = os.path.join(tempfile.gettempdir(), "chatterbox_tts_output.wav")
            audio = results[0].audio
            if hasattr(audio, 'numpy'):
                audio = audio.numpy()
            sr = getattr(self._chatterbox_model, 'sample_rate', 24000)
            sf.write(temp_path, np.array(audio).flatten(), sr)

            if not self._stop_requested:
                self._play_audio_file(temp_path)

        except ImportError as e:
            missing = str(e)
            if self._on_error:
                self._on_error(
                    f"Chatterbox Turbo requires the mlx-audio package.\n"
                    f"Missing: {missing}\n\n"
                    f"Install with:\n"
                    f"  pip install mlx-audio soundfile"
                )
        except Exception as e:
            if self._on_error:
                self._on_error(f"Chatterbox Turbo error: {e}")
        finally:
            self._is_speaking = False
            if self._on_end:
                self._on_end()

    def _speak_kokoro(self, text: str):
        """Speak using Kokoro TTS via kokoro-onnx (runs in thread).

        Downloads model files (~200MB) on first use.
        82M parameters — fast even on CPU.
        """
        try:
            if self._on_progress:
                self._on_progress("Loading Kokoro...")

            from kokoro_onnx import Kokoro
            import soundfile as sf

            # Cache the Kokoro instance
            if not hasattr(self, '_kokoro_instance') or self._kokoro_instance is None:
                # Model files stored in ~/.writer_platform/kokoro/
                model_dir = Path.home() / ".writer_platform" / "kokoro"
                model_dir.mkdir(parents=True, exist_ok=True)

                model_path = model_dir / "kokoro-v1.0.onnx"
                voices_path = model_dir / "voices-v1.0.bin"

                # Download model files if not present
                if not model_path.exists() or not voices_path.exists():
                    print("[TTS] Downloading Kokoro model files (~200MB)...")
                    if self._on_progress:
                        self._on_progress("Downloading Kokoro model...")
                    import requests
                    base_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

                    if not model_path.exists():
                        r = requests.get(f"{base_url}/kokoro-v1.0.onnx", stream=True)
                        r.raise_for_status()
                        with open(model_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)

                    if not voices_path.exists():
                        r = requests.get(f"{base_url}/voices-v1.0.bin", stream=True)
                        r.raise_for_status()
                        with open(voices_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)

                    print("[TTS] Kokoro model files downloaded")

                print("[TTS] Loading Kokoro ONNX model...")
                self._kokoro_instance = Kokoro(str(model_path), str(voices_path))
                print("[TTS] Kokoro ready")

            if self._stop_requested:
                return

            voice = self._voice_id if self._voice_id else "af_heart"

            if self._on_progress:
                self._on_progress("Generating speech...")

            # Map WPM rate to Kokoro speed multiplier (150 WPM = 1.0x)
            speed = max(0.5, min(2.0, self._rate / 150.0)) if self._rate else 1.0
            samples, sample_rate = self._kokoro_instance.create(
                text, voice=voice, speed=speed
            )

            if self._stop_requested:
                return

            temp_path = os.path.join(tempfile.gettempdir(), "kokoro_tts_output.wav")
            sf.write(temp_path, samples, sample_rate)

            if not self._stop_requested:
                self._play_audio_file(temp_path)

        except ImportError:
            if self._on_error:
                self._on_error(
                    "Kokoro TTS not installed.\n\n"
                    "Install with:\n"
                    "  pip install kokoro-onnx soundfile\n\n"
                    "The model (~200MB) downloads automatically on first use."
                )
        except Exception as e:
            if self._on_error:
                self._on_error(f"Kokoro error: {e}")
        finally:
            self._is_speaking = False
            if self._on_end:
                self._on_end()

    def _play_audio_file(self, file_path: str):
        """Play an audio file using system audio.

        Uses subprocess with Popen (non-blocking) so stop() can kill it.
        """
        try:
            import subprocess
            import platform

            system = platform.system()
            if system == "Windows":
                proc = subprocess.Popen(
                    ['powershell', '-c', f'(New-Object Media.SoundPlayer "{file_path}").PlaySync()'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            elif system == "Darwin":
                proc = subprocess.Popen(
                    ['afplay', file_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            else:
                proc = subprocess.Popen(
                    ['aplay', file_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )

            # Store the process so stop() can kill it
            self._audio_proc = proc

            # Poll instead of blocking — check stop flag every 100ms
            while proc.poll() is None:
                if self._stop_requested:
                    proc.terminate()
                    proc.wait(timeout=2)
                    return
                import time
                time.sleep(0.1)

        except Exception as e:
            print(f"Error playing audio: {e}")
            if self._on_error:
                self._on_error(f"Audio playback error: {e}")
        finally:
            self._audio_proc = None

    def stop(self):
        """Stop speaking immediately."""
        self._stop_requested = True

        # Kill audio playback subprocess
        proc = getattr(self, '_audio_proc', None)
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

        # Kill macOS 'say' subprocess if it is active
        macos_proc = getattr(self, '_macos_say_proc', None)
        if macos_proc is not None:
            self._macos_say_proc = None
            try:
                macos_proc.terminate()
            except Exception:
                pass

        # Cancel AVSpeechSynthesizer if active (macOS Siri voices)
        av_synth = getattr(self, '_avspeech_synth', None)
        if av_synth is not None:
            try:
                av_synth.stopSpeakingAtBoundary_(0)  # AVSpeechBoundaryImmediate
            except Exception:
                pass
            self._avspeech_synth = None

        if self._current_engine == TTSEngine.SYSTEM and self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.stop()
                self._pyttsx3_engine = None
            except:
                pass

        # Wait briefly for the speech thread to notice _stop_requested,
        # then abandon it if it's stuck in a blocking generation call.
        thread = self._speech_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)
            # If still alive, it's stuck generating — detach and move on.
            # The daemon thread will finish on its own; we just stop waiting.
            if thread.is_alive():
                print("[TTS] Speech thread did not stop in time — detaching")
        self._speech_thread = None

        self._is_speaking = False
        self._is_paused = False

        # Call end callback to ensure UI is updated
        if self._on_end:
            self._on_end()

    def speak_to_file(self, text: str, output_path: str) -> bool:
        """Save speech to an audio file.

        Args:
            text: Text to convert to speech
            output_path: Path to save the audio file

        Returns:
            True if successful
        """
        try:
            if self._current_engine == TTSEngine.VIBEVOICE:
                import subprocess
                import sys

                vibevoice_path = self._vibevoice_path or str(Path.home() / "VibeVoice")

                # Create a temporary text file for input
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as txt_file:
                    txt_file.write(text)
                    text_path = txt_file.name

                script_path = Path(vibevoice_path) / "demo" / "inference_from_file.py"

                model_map = {
                    "0.5B": "VibeVoice-0.5B",
                    "1.5B": "VibeVoice-1.5B",
                    "7B": "VibeVoice-7B"
                }
                model_name = model_map.get(self._vibevoice_model, "VibeVoice-1.5B")

                cmd = [
                    sys.executable,
                    str(script_path),
                    "--model_path", f"vibevoice/{model_name}",
                    "--txt_path", text_path,
                    "--speaker_names", self._vibevoice_voice.capitalize(),
                    "--output_path", output_path,
                ]

                result = subprocess.run(
                    cmd,
                    cwd=vibevoice_path,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout for saving
                )

                try:
                    os.unlink(text_path)
                except:
                    pass

                return result.returncode == 0

            elif self._current_engine == TTSEngine.EDGE:
                import edge_tts

                async def save():
                    communicate = edge_tts.Communicate(text, self._edge_voice)
                    await communicate.save(output_path)

                asyncio.run(save())
                return True

            elif self._current_engine == TTSEngine.SYSTEM:
                self._init_pyttsx3()
                if self._pyttsx3_engine:
                    self._pyttsx3_engine.save_to_file(text, output_path)
                    self._pyttsx3_engine.runAndWait()
                    return True

        except Exception as e:
            print(f"Error saving speech to file: {e}")
            if self._on_error:
                self._on_error(str(e))

        return False


# Global instance
_tts_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    """Get global TTS service instance."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
