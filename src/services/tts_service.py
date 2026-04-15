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
    HIGGS_AUDIO = "higgs_audio"  # Higgs Audio V2 - high-quality neural TTS from Boson AI
    KOKORO = "kokoro"  # Kokoro - 82M param high-quality local TTS


@dataclass
class TTSVoice:
    """Represents a TTS voice."""
    id: str
    name: str
    language: str
    gender: str
    engine: TTSEngine


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
        elif engine == TTSEngine.HIGGS_AUDIO:
            voices.extend(self._get_higgs_audio_voices())
        elif engine == TTSEngine.KOKORO:
            voices.extend(self._get_kokoro_voices())

        return voices

    def _get_pyttsx3_voices(self) -> List[TTSVoice]:
        """Get pyttsx3 voices."""
        self._init_pyttsx3()
        if not self._pyttsx3_engine:
            return []

        voices = []
        try:
            for voice in self._pyttsx3_engine.getProperty('voices'):
                # Parse voice info
                name = voice.name
                lang = getattr(voice, 'languages', ['en'])[0] if hasattr(voice, 'languages') else 'en'
                if isinstance(lang, bytes):
                    lang = lang.decode('utf-8', errors='ignore')

                # Guess gender from name
                gender = "female" if any(f in name.lower() for f in ['zira', 'hazel', 'susan', 'female']) else "male"

                voices.append(TTSVoice(
                    id=voice.id,
                    name=name,
                    language=str(lang)[:5],
                    gender=gender,
                    engine=TTSEngine.SYSTEM
                ))
        except Exception as e:
            print(f"Error getting pyttsx3 voices: {e}")

        return voices

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

    def _get_higgs_audio_voices(self) -> List[TTSVoice]:
        """Get Higgs Audio V2 voices (uses model's built-in voice generation)."""
        voices = [
            TTSVoice("default", "Default (Neural)", "en", "neutral", TTSEngine.HIGGS_AUDIO),
        ]
        return voices

    def _get_kokoro_voices(self) -> List[TTSVoice]:
        """Get Kokoro voice presets."""
        voices = [
            TTSVoice("af_heart", "Heart (warm, natural)", "en-US", "female", TTSEngine.KOKORO),
            TTSVoice("af_bella", "Bella (clear, bright)", "en-US", "female", TTSEngine.KOKORO),
            TTSVoice("af_sarah", "Sarah (calm, steady)", "en-US", "female", TTSEngine.KOKORO),
            TTSVoice("af_nicole", "Nicole (smooth)", "en-US", "female", TTSEngine.KOKORO),
            TTSVoice("af_sky", "Sky (light, airy)", "en-US", "female", TTSEngine.KOKORO),
            TTSVoice("af_nova", "Nova (energetic)", "en-US", "female", TTSEngine.KOKORO),
            TTSVoice("am_adam", "Adam (deep, warm)", "en-US", "male", TTSEngine.KOKORO),
            TTSVoice("am_michael", "Michael (clear)", "en-US", "male", TTSEngine.KOKORO),
            TTSVoice("bf_emma", "Emma (British)", "en-GB", "female", TTSEngine.KOKORO),
            TTSVoice("bm_george", "George (British)", "en-GB", "male", TTSEngine.KOKORO),
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

    def speak(self, text: str):
        """Speak text using the current engine (non-blocking)."""
        # Always reset state first - this ensures we can start fresh
        self._stop_requested = False

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
        elif self._current_engine == TTSEngine.HIGGS_AUDIO:
            self._speech_thread = threading.Thread(
                target=self._speak_higgs_audio,
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

    def _speak_macos_say(self, text: str):
        """Speak using macOS built-in 'say' command (blocks until audio is done).

        This bypasses pyttsx3's unreliable runAndWait() on macOS, where the
        method may return before the OS finishes playing queued audio.
        """
        import subprocess

        cmd = ['say']

        # Extract voice name from pyttsx3-style voice ID if set.
        # pyttsx3 IDs on macOS look like:
        #   "com.apple.speech.synthesis.voice.samantha.premium"
        # The 'say' command accepts the voice name portion (e.g. "Samantha").
        if self._voice_id:
            skip = {'premium', 'compact', 'enhanced', 'com', 'apple',
                    'speech', 'synthesis', 'voice', ''}
            for part in reversed(self._voice_id.split('.')):
                if part.lower() not in skip:
                    cmd.extend(['-v', part.capitalize()])
                    break

        # Pass speech rate (words per minute — same unit as pyttsx3)
        if self._rate:
            cmd.extend(['--rate', str(int(self._rate))])

        # Launch 'say', feeding text via stdin to handle any length
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._macos_say_proc = proc

        try:
            proc.stdin.write(text.encode('utf-8', errors='replace'))
            proc.stdin.close()

            # Wait for completion, honouring stop requests
            while True:
                try:
                    proc.wait(timeout=0.1)
                    break  # Process finished naturally
                except subprocess.TimeoutExpired:
                    if self._stop_requested:
                        proc.terminate()
                        try:
                            proc.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break
        finally:
            self._macos_say_proc = None

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

    def _speak_higgs_audio(self, text: str):
        """Speak using Higgs Audio V2 (runs in thread).

        Downloads the model from HuggingFace on first use.
        Uses transformers pipeline for generation.
        """
        try:
            if self._on_progress:
                self._on_progress("Loading Higgs Audio V2...")

            import torch
            from transformers import pipeline

            # Use a cached pipeline — only load once
            if not hasattr(self, '_higgs_pipeline') or self._higgs_pipeline is None:
                print("[TTS] Loading Higgs Audio V2 model (will download on first use)...")

                # Get HF token if available
                hf_token = None
                try:
                    from src.config.credential_manager import get_credential_manager
                    hf_token = get_credential_manager().get_huggingface_token()
                except Exception:
                    pass

                self._higgs_pipeline = pipeline(
                    "text-to-audio",
                    model="bosonai/higgs-audio-v2-generation-3B-base",
                    torch_dtype=torch.bfloat16,
                    device="mps" if torch.backends.mps.is_available() else "cpu",
                    token=hf_token
                )
                print("[TTS] Higgs Audio V2 loaded")

            if self._stop_requested:
                return

            if self._on_progress:
                self._on_progress("Generating speech...")

            # Generate audio
            output = self._higgs_pipeline(text)

            if self._stop_requested:
                return

            # Save to temp file and play
            import soundfile as sf
            temp_path = os.path.join(tempfile.gettempdir(), "higgs_tts_output.wav")

            audio_data = output["audio"]
            sample_rate = output["sampling_rate"]

            # Handle different output shapes
            import numpy as np
            if isinstance(audio_data, torch.Tensor):
                audio_data = audio_data.cpu().numpy()
            if isinstance(audio_data, np.ndarray):
                if audio_data.ndim > 1:
                    audio_data = audio_data.squeeze()

            sf.write(temp_path, audio_data, sample_rate)

            if not self._stop_requested:
                self._play_audio_file(temp_path)

        except ImportError as e:
            missing = str(e)
            if self._on_error:
                self._on_error(
                    f"Higgs Audio V2 requires additional packages.\n"
                    f"Missing: {missing}\n\n"
                    f"Install with:\n"
                    f"  pip install transformers torch soundfile"
                )
        except Exception as e:
            if self._on_error:
                self._on_error(f"Higgs Audio V2 error: {e}")
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

            samples, sample_rate = self._kokoro_instance.create(
                text, voice=voice, speed=1.0
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

        if self._current_engine == TTSEngine.SYSTEM and self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.stop()
                self._pyttsx3_engine = None
            except:
                pass

        self._is_speaking = False

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
