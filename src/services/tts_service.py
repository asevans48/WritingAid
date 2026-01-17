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
            import pyttsx3
            return True
        except ImportError:
            return False

    def _check_edge_tts(self) -> bool:
        """Check if edge-tts is available."""
        try:
            import edge_tts
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
            # Check common installation paths
            common_paths = [
                Path.home() / "VibeVoice",
                Path.home() / ".vibevoice",
                Path("C:/VibeVoice") if os.name == 'nt' else Path("/opt/vibevoice"),
            ]
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
        """Get edge-tts voices (common ones for quick access)."""
        # Return a curated list of popular edge voices
        # Full list requires async call to edge_tts.list_voices()
        common_voices = [
            TTSVoice("en-US-AriaNeural", "Aria (US)", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-US-GuyNeural", "Guy (US)", "en-US", "male", TTSEngine.EDGE),
            TTSVoice("en-US-JennyNeural", "Jenny (US)", "en-US", "female", TTSEngine.EDGE),
            TTSVoice("en-GB-SoniaNeural", "Sonia (UK)", "en-GB", "female", TTSEngine.EDGE),
            TTSVoice("en-GB-RyanNeural", "Ryan (UK)", "en-GB", "male", TTSEngine.EDGE),
            TTSVoice("en-AU-NatashaNeural", "Natasha (AU)", "en-AU", "female", TTSEngine.EDGE),
            TTSVoice("en-CA-ClaraNeural", "Clara (CA)", "en-CA", "female", TTSEngine.EDGE),
            TTSVoice("en-IN-NeerjaNeural", "Neerja (IN)", "en-IN", "female", TTSEngine.EDGE),
        ]
        return common_voices

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
        else:
            self._speech_thread = threading.Thread(
                target=self._speak_edge,
                args=(text,),
                daemon=True
            )

        self._speech_thread.start()

    def _speak_pyttsx3(self, text: str):
        """Speak using pyttsx3 (runs in thread)."""
        try:
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

    def _play_audio_file(self, file_path: str):
        """Play an audio file using system audio."""
        try:
            # Try pygame first (cross-platform)
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.set_volume(self._volume)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy() and not self._stop_requested:
                    pygame.time.wait(100)
                pygame.mixer.music.stop()
                return
            except ImportError:
                pass

            # Fallback: use system commands
            import subprocess
            import platform

            system = platform.system()
            if system == "Windows":
                # Use Windows Media Player
                subprocess.run(
                    ['powershell', '-c', f'(New-Object Media.SoundPlayer "{file_path}").PlaySync()'],
                    capture_output=True
                )
            elif system == "Darwin":  # macOS
                subprocess.run(['afplay', file_path], capture_output=True)
            else:  # Linux
                subprocess.run(['aplay', file_path], capture_output=True)

        except Exception as e:
            print(f"Error playing audio: {e}")
            if self._on_error:
                self._on_error(f"Audio playback error: {e}")

    def stop(self):
        """Stop speaking."""
        self._stop_requested = True

        if self._current_engine == TTSEngine.SYSTEM and self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.stop()
                # Re-initialize pyttsx3 to clear its state after stop
                # This prevents issues where the engine won't speak after being stopped
                self._pyttsx3_engine = None
            except:
                pass

        # Stop pygame audio if it's playing
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except:
            pass

        self._is_speaking = False

        # Call end callback to ensure UI is updated
        if self._on_end:
            self._on_end()

    def pause(self):
        """Pause speaking (if supported)."""
        # pyttsx3 doesn't support pause well
        # For edge-tts, we'd need to track position
        pass

    def resume(self):
        """Resume speaking (if supported)."""
        pass

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
