"""Speech-to-text service using speech_recognition library."""

import threading
from typing import Optional, Callable

try:
    import speech_recognition as sr
    STT_AVAILABLE = True
except ImportError:
    STT_AVAILABLE = False


class STTService:
    """Microphone speech-to-text using Google Speech Recognition."""

    def __init__(self):
        self._recognizer = sr.Recognizer() if STT_AVAILABLE else None
        self._microphone = None
        self._listening = False
        self._thread: Optional[threading.Thread] = None
        self.on_result: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_listening: Optional[Callable[[bool], None]] = None

    @staticmethod
    def is_available() -> bool:
        return STT_AVAILABLE

    def is_listening(self) -> bool:
        return self._listening

    def start(self):
        """Start listening for speech in a background thread."""
        if not STT_AVAILABLE:
            if self.on_error:
                self.on_error("speech_recognition not installed. Run: pip install SpeechRecognition")
            return
        if self._listening:
            return

        self._listening = True
        if self.on_listening:
            self.on_listening(True)

        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop listening."""
        self._listening = False
        if self.on_listening:
            self.on_listening(False)

    def _listen(self):
        """Capture audio from microphone and transcribe."""
        try:
            mic = sr.Microphone()
            with mic as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(source, timeout=10, phrase_time_limit=30)

            # Transcribe
            text = self._recognizer.recognize_google(audio)
            self._listening = False
            if self.on_listening:
                self.on_listening(False)
            if self.on_result and text:
                self.on_result(text)

        except sr.WaitTimeoutError:
            self._listening = False
            if self.on_listening:
                self.on_listening(False)
            if self.on_error:
                self.on_error("No speech detected. Try again.")
        except sr.UnknownValueError:
            self._listening = False
            if self.on_listening:
                self.on_listening(False)
            if self.on_error:
                self.on_error("Could not understand audio. Try again.")
        except sr.RequestError as e:
            self._listening = False
            if self.on_listening:
                self.on_listening(False)
            if self.on_error:
                self.on_error(f"Speech recognition service error: {e}")
        except Exception as e:
            self._listening = False
            if self.on_listening:
                self.on_listening(False)
            if self.on_error:
                self.on_error(f"Microphone error: {e}")


# Singleton
_stt_instance: Optional[STTService] = None


def get_stt_service() -> STTService:
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = STTService()
    return _stt_instance
