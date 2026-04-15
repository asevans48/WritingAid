"""Speech-to-text service with multiple engine support.

Engines (in preference order):
- Whisper (local, via faster-whisper or openai-whisper)
- Moonshine (local, ultra-fast edge model)
- Google Speech Recognition (online, via speech_recognition)

Only ONE local model is loaded at a time. Switching engine or model size
unloads the previous model first to avoid overrunning memory.
"""

import gc
import threading
import logging
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger(__name__)

try:
    import speech_recognition as sr
    _SR_AVAILABLE = True
except ImportError:
    _SR_AVAILABLE = False


class STTEngine(str, Enum):
    AUTO = "auto"
    WHISPER_LOCAL = "whisper_local"
    MOONSHINE = "moonshine"
    GOOGLE = "google"


def _detect_best_engine() -> STTEngine:
    try:
        import faster_whisper
        return STTEngine.WHISPER_LOCAL
    except ImportError:
        pass
    try:
        import whisper
        return STTEngine.WHISPER_LOCAL
    except ImportError:
        pass
    try:
        import moonshine
        return STTEngine.MOONSHINE
    except ImportError:
        pass
    return STTEngine.GOOGLE


class STTService:
    """Microphone speech-to-text with single-model memory management."""

    def __init__(self):
        self._recognizer = sr.Recognizer() if _SR_AVAILABLE else None
        self._listening = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Engine config
        self._engine = STTEngine.AUTO
        self._whisper_model_size = "base"

        # Loaded model state — only ONE at a time
        self._loaded_model = None
        self._loaded_model_type = None
        self._loaded_model_size = None

        # Callbacks
        self.on_result: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_listening: Optional[Callable[[bool], None]] = None

        # Register cleanup on interpreter shutdown
        import atexit
        atexit.register(self.shutdown)

    @staticmethod
    def is_available() -> bool:
        return _SR_AVAILABLE

    @staticmethod
    def get_available_engines() -> list:
        engines = []
        try:
            import faster_whisper
            engines.append(("Whisper (faster-whisper)", STTEngine.WHISPER_LOCAL, True))
        except ImportError:
            try:
                import whisper
                engines.append(("Whisper (openai)", STTEngine.WHISPER_LOCAL, True))
            except ImportError:
                engines.append(("Whisper (not installed)", STTEngine.WHISPER_LOCAL, False))
        try:
            import moonshine
            engines.append(("Moonshine (edge)", STTEngine.MOONSHINE, True))
        except ImportError:
            engines.append(("Moonshine (not installed)", STTEngine.MOONSHINE, False))
        engines.append(("Google (online)", STTEngine.GOOGLE, _SR_AVAILABLE))
        return engines

    def set_engine(self, engine: STTEngine):
        if engine != self._engine:
            self._engine = engine
            # Unload current model if switching away from it
            if engine == STTEngine.GOOGLE:
                self._unload_model()

    def set_whisper_model_size(self, size: str):
        if size != self._whisper_model_size:
            old_size = self._whisper_model_size
            self._whisper_model_size = size
            # Unload if we had a different whisper model loaded
            if (self._loaded_model_type in ("faster_whisper", "whisper")
                    and self._loaded_model_size != size):
                logger.info(f"Whisper model size changed {old_size} → {size}, unloading old model")
                self._unload_model()

    def _unload_model(self):
        """Unload the current STT model to free memory."""
        if self._loaded_model is not None:
            logger.info(f"Unloading STT model: {self._loaded_model_type} ({self._loaded_model_size})")
            del self._loaded_model
            self._loaded_model = None
            self._loaded_model_type = None
            self._loaded_model_size = None
            gc.collect()

    def is_listening(self) -> bool:
        return self._listening

    def start(self):
        if not _SR_AVAILABLE:
            if self.on_error:
                self.on_error("speech_recognition not installed. Run: pip install SpeechRecognition PyAudio")
            return
        if self._listening:
            return

        self._listening = True
        self._stop_event.clear()
        if self.on_listening:
            self.on_listening(True)

        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop listening immediately."""
        self._listening = False
        self._stop_event.set()
        if self.on_listening:
            self.on_listening(False)

    def shutdown(self):
        """Clean shutdown — stop listening and unload model."""
        self.stop()
        self._unload_model()
        # Wait briefly for thread to exit
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _listen(self):
        try:
            mic = sr.Microphone()
            with mic as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)

                if self._stop_event.is_set():
                    return

                # Use shorter timeout so stop() can interrupt between retries
                audio = self._recognizer.listen(
                    source, timeout=10, phrase_time_limit=60
                )

            if self._stop_event.is_set():
                return

            engine = self._engine
            if engine == STTEngine.AUTO:
                engine = _detect_best_engine()

            print(f"[STT] Transcribing with engine: {engine.value}")

            if engine == STTEngine.WHISPER_LOCAL:
                text = self._transcribe_whisper(audio)
            elif engine == STTEngine.MOONSHINE:
                text = self._transcribe_moonshine(audio)
            else:
                text = self._transcribe_google(audio)

            if self._stop_event.is_set():
                return

            self._listening = False
            if self.on_listening:
                self.on_listening(False)
            if self.on_result and text:
                self.on_result(text)

        except sr.WaitTimeoutError:
            if not self._stop_event.is_set():
                self._finish_with_error("No speech detected. Try again.")
        except sr.UnknownValueError:
            if not self._stop_event.is_set():
                self._finish_with_error("Could not understand audio. Try again.")
        except sr.RequestError as e:
            if not self._stop_event.is_set():
                self._finish_with_error(f"Speech recognition service error: {e}")
        except Exception as e:
            if not self._stop_event.is_set():
                self._finish_with_error(f"Microphone error: {e}")

    def _finish_with_error(self, msg: str):
        self._listening = False
        if self.on_listening:
            self.on_listening(False)
        if self.on_error:
            self.on_error(msg)

    def _ensure_whisper_model(self):
        """Load the whisper model if not already loaded (or if size changed).

        Unloads any other model type first. Downloads from HuggingFace
        on first use of a given model size.
        """
        target_size = self._whisper_model_size

        # Check if we already have the right model loaded
        if (self._loaded_model is not None
                and self._loaded_model_type in ("faster_whisper", "whisper")
                and self._loaded_model_size == target_size):
            return

        # Unload any existing model first (only one model at a time)
        self._unload_model()

        # Try faster-whisper first
        try:
            from faster_whisper import WhisperModel

            logger.info(f"Loading faster-whisper model: {target_size} "
                        f"(will download from HuggingFace if not cached)")
            print(f"[STT] Loading faster-whisper '{target_size}'...")

            self._loaded_model = WhisperModel(
                target_size,
                device="auto",
                compute_type="int8"
            )
            self._loaded_model_type = "faster_whisper"
            self._loaded_model_size = target_size
            print(f"[STT] faster-whisper '{target_size}' ready")
            return
        except ImportError:
            pass

        # Try standard whisper
        try:
            import whisper

            logger.info(f"Loading whisper model: {target_size} "
                        f"(will download from OpenAI if not cached)")
            print(f"[STT] Loading whisper '{target_size}'...")

            self._loaded_model = whisper.load_model(target_size)
            self._loaded_model_type = "whisper"
            self._loaded_model_size = target_size
            print(f"[STT] whisper '{target_size}' ready")
            return
        except ImportError:
            pass

        raise RuntimeError(
            "No Whisper library installed. Run:\n"
            "  pip install faster-whisper   (recommended)\n"
            "  pip install openai-whisper   (alternative)"
        )

    def _ensure_moonshine_model(self):
        """Load the moonshine model if not already loaded."""
        if self._loaded_model_type == "moonshine" and self._loaded_model is not None:
            return

        self._unload_model()

        try:
            import moonshine
            # Moonshine doesn't need explicit loading — it loads on first transcribe
            self._loaded_model = moonshine
            self._loaded_model_type = "moonshine"
            self._loaded_model_size = "default"
            print("[STT] Moonshine ready")
        except ImportError:
            raise RuntimeError("Moonshine not installed. Run: pip install moonshine")

    def _transcribe_whisper(self, audio) -> str:
        import tempfile
        import os

        self._ensure_whisper_model()
        wav_data = audio.get_wav_data()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_data)
            tmp_path = f.name

        try:
            if self._loaded_model_type == "faster_whisper":
                segments, _ = self._loaded_model.transcribe(tmp_path)
                return " ".join(seg.text for seg in segments).strip()
            else:
                # Standard whisper
                result = self._loaded_model.transcribe(tmp_path)
                return result["text"].strip()
        finally:
            os.unlink(tmp_path)

    def _transcribe_moonshine(self, audio) -> str:
        import tempfile
        import os

        self._ensure_moonshine_model()
        wav_data = audio.get_wav_data()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_data)
            tmp_path = f.name

        try:
            text = self._loaded_model.transcribe(tmp_path)
            if isinstance(text, list):
                text = " ".join(text)
            return text.strip()
        finally:
            os.unlink(tmp_path)

    def _transcribe_google(self, audio) -> str:
        return self._recognizer.recognize_google(audio)


# Singleton
_stt_instance: Optional[STTService] = None


def get_stt_service() -> STTService:
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = STTService()
    return _stt_instance
