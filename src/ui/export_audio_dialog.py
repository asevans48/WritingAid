"""Dialog for exporting chapters as audio files.

Pipeline:
1. Chunk text at natural breaks (paragraphs, respecting size limits)
2. Optionally format text for speech via LLM (expand abbreviations, etc.)
3. Generate audio per chunk with the chosen engine
4. Concatenate chunks into chapter or book-level files
"""

from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QRadioButton, QButtonGroup, QFileDialog,
    QListWidget, QListWidgetItem, QProgressBar, QGroupBox,
    QFormLayout, QLineEdit, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from typing import List, Optional
import numpy as np
import re


# ── Text chunking ────────────────────────────────────────────────

# Scene break markers to strip (not speech content)
_SCENE_BREAKS = {'***', '---', '* * *', '—', '⁂'}

# Max chars per chunk for each TTS engine.
# Sized to fit within the engine's internal context window so it never
# needs to do its own splitting (which can lose content at boundaries).
ENGINE_CHUNK_SIZES = {
    "kokoro":     400,   # 510 phoneme limit (~450 chars); stay under
    "chatterbox": 350,   # 800 token limit (~400 chars); stay under
    "edge":       2000,  # Microsoft neural TTS handles long text
    "system":     5000,  # macOS `say` handles unlimited text
}


def _word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def _chunk_text(text: str, max_chars: int = 2000) -> List[str]:
    """Split text into sequential chunks respecting the engine's context limit.

    Rules:
    - Never break in the middle of a sentence.
    - If adding a sentence would exceed max_chars, push that sentence
      to start the next chunk.
    - Every word in the input appears in exactly one output chunk.

    Strategy:
    1. Strip scene breaks.
    2. Split into sentences (preserving paragraph gaps as markers).
    3. Group sentences into chunks, never exceeding max_chars.
    4. Verify word count.
    """
    if not text or not text.strip():
        return []

    # Strip scene break markers
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip() in _SCENE_BREAKS:
            cleaned_lines.append('')
        else:
            cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)

    input_words = _word_count(text)

    if len(text) <= max_chars:
        return [text.strip()] if text.strip() else []

    # ── Step 1: Split into sentences ──
    # We track paragraph gaps so chunks prefer to break there.
    sentences = _split_into_sentences(text)

    # ── Step 2: Group sentences into chunks ──
    chunks = []
    current = ""

    for sent in sentences:
        if not sent.strip():
            continue

        # Would adding this sentence overflow the current chunk?
        if current:
            combined_len = len(current) + 1 + len(sent)  # +1 for space
        else:
            combined_len = len(sent)

        if current and combined_len > max_chars:
            # Flush current chunk; this sentence starts the next one
            chunks.append(current.strip())
            current = ""

        # If a single sentence exceeds max_chars, split it at words
        if len(sent) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for sub in _split_at_words(sent, max_chars):
                chunks.append(sub)
        else:
            current = f"{current} {sent}" if current else sent

    if current and current.strip():
        chunks.append(current.strip())

    # ── Step 3: Verify no chunk exceeds the limit ──
    final = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final.append(chunk)
        else:
            final.extend(_split_at_words(chunk, max_chars))
    chunks = final

    # ── Step 4: Word-count verification ──
    output_words = sum(_word_count(c) for c in chunks)
    if output_words != input_words:
        print(f"[AudioExport] CHUNK WARNING: input={input_words} words, "
              f"output={output_words} words (delta={input_words - output_words})")
        if output_words < input_words:
            chunks = _split_at_words(text.strip(), max_chars)
            fallback_words = sum(_word_count(c) for c in chunks)
            print(f"[AudioExport] CHUNK FALLBACK: word-split -> "
                  f"{len(chunks)} chunks, {fallback_words} words")

    return chunks


def _split_into_sentences(text: str) -> List[str]:
    """Split text into sentences, keeping each sentence whole.

    Handles:
    - Standard sentence endings: . ! ?
    - Abbreviations: Dr. Mr. Mrs. Ms. St. etc. (not split)
    - Dialogue: "Hello." she said
    - Ellipsis: ... (not split)
    - Paragraph breaks preserved as sentence boundaries
    """
    # Common abbreviations that end with a period but aren't sentence ends
    abbrevs = {'dr', 'mr', 'mrs', 'ms', 'st', 'jr', 'sr', 'prof', 'gen',
               'sgt', 'cpl', 'pvt', 'lt', 'col', 'capt', 'cmdr', 'adm',
               'gov', 'pres', 'rev', 'hon', 'dept', 'univ', 'assn',
               'bros', 'inc', 'ltd', 'co', 'corp', 'vs', 'etc', 'approx',
               'appt', 'apt', 'ave', 'blvd', 'bldg', 'dept', 'est',
               'fig', 'ft', 'hwy', 'mt', 'no', 'oz', 'pkg', 'rd',
               'sq', 'vol', 'ct', 'pt'}

    sentences = []
    current = ""

    # Split on paragraph breaks first — each paragraph is independent
    paragraphs = text.split('\n')

    for para in paragraphs:
        para = para.strip()
        if not para:
            # Paragraph break: flush current sentence
            if current.strip():
                sentences.append(current.strip())
                current = ""
            continue

        # Walk through the paragraph character by character
        i = 0
        while i < len(para):
            current += para[i]

            # Check for sentence end
            if para[i] in '.!?' and i + 1 < len(para):
                next_char = para[i + 1]

                # Skip ellipsis (...)
                if para[i] == '.' and i + 1 < len(para) and para[i + 1] == '.':
                    i += 1
                    continue

                # Check if this is an abbreviation (word before period)
                if para[i] == '.':
                    # Get the word before the period
                    word_before = current.rstrip('.').split()[-1].lower() if current.rstrip('.').split() else ''
                    if word_before in abbrevs:
                        i += 1
                        continue

                # Sentence end if followed by space then uppercase or quote
                if next_char in ' \t':
                    # Look ahead past whitespace for uppercase/quote
                    j = i + 1
                    while j < len(para) and para[j] in ' \t':
                        j += 1
                    if j < len(para) and (para[j].isupper() or para[j] in '"\'"\u201c\u2018('):
                        sentences.append(current.strip())
                        current = ""

            i += 1

        # End of paragraph line — add a space to separate from next line
        if current and not current.endswith(' '):
            current += ' '

    # Flush remaining
    if current.strip():
        sentences.append(current.strip())

    return sentences

    return parts


def _split_at_words(text: str, max_chars: int) -> List[str]:
    """Last-resort split: break at word boundaries. Loses zero words."""
    words = text.split()
    chunks = []
    current_words = []
    current_len = 0

    for word in words:
        word_len = len(word)
        space = 1 if current_words else 0
        if current_words and current_len + space + word_len > max_chars:
            chunks.append(' '.join(current_words))
            current_words = []
            current_len = 0
        current_words.append(word)
        current_len += (1 if len(current_words) > 1 else 0) + word_len

    if current_words:
        chunks.append(' '.join(current_words))

    return chunks


# ── Export worker ────────────────────────────────────────────────

class _ExportWorker(QThread):
    """Background worker for the full export pipeline."""

    progress = pyqtSignal(str, int, int)  # message, current, total
    finished = pyqtSignal(int)  # files_created
    error = pyqtSignal(str)

    def __init__(self, chapters: list, engine: str, voice: str,
                 output_dir: str, per_chapter: bool, format_with_llm: bool):
        super().__init__()
        self.chapters = chapters
        self.engine = engine
        self.voice = voice
        self.output_dir = output_dir
        self.per_chapter = per_chapter
        self.format_with_llm = format_with_llm
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import soundfile as sf
            out_dir = Path(self.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            multi_chapter = len(self.chapters) > 1
            from src.ui.enhanced_text_editor import strip_markdown

            # Use engine-specific chunk size to stay within context window
            chunk_size = ENGINE_CHUNK_SIZES.get(self.engine, 400)
            print(f"[AudioExport] Engine={self.engine}, "
                  f"chunk_size={chunk_size} chars")

            # ── Build work list: [(chapter, [chunk, ...]), ...] ──
            all_chapter_chunks = []
            for ch in self.chapters:
                content = getattr(ch, 'content', '') or ''
                if not content.strip():
                    print(f"[AudioExport] Ch{getattr(ch, 'number', '?')} "
                          f"'{getattr(ch, 'title', '?')}': SKIPPED (no content)")
                    continue

                plain = strip_markdown(content)
                chunks = _chunk_text(plain, max_chars=chunk_size)
                if chunks:
                    total_chars = sum(len(c) for c in chunks)
                    number = getattr(ch, 'number', '?')
                    title = getattr(ch, 'title', '?')
                    # Verify nothing was lost in chunking
                    plain_stripped = plain.strip()
                    rejoined = "\n\n".join(chunks).strip()
                    if len(rejoined) < len(plain_stripped) * 0.95:
                        print(f"[AudioExport] WARNING Ch{number}: chunking "
                              f"lost text! plain={len(plain_stripped)} "
                              f"chunks={len(rejoined)}")
                    print(f"[AudioExport] Ch{number} '{title}': "
                          f"{len(content)} raw -> {len(plain)} plain -> "
                          f"{len(chunks)} chunks ({total_chars} chars)")
                    for ci, chunk in enumerate(chunks):
                        print(f"[AudioExport]   chunk {ci+1}: {len(chunk)} chars, "
                              f"starts: {repr(chunk[:60])}")
                    all_chapter_chunks.append((ch, chunks))

            if not all_chapter_chunks:
                self.finished.emit(0)
                return

            # Extra chunks for chapter headers in multi-chapter exports
            header_count = len(all_chapter_chunks) if multi_chapter else 0
            total_chunks = header_count + sum(
                len(chunks) for _, chunks in all_chapter_chunks)
            print(f"[AudioExport] Total: {len(all_chapter_chunks)} chapters, "
                  f"{total_chunks} chunks, engine={self.engine}")

            chunk_idx = 0
            files_created = 0

            if self.per_chapter:
                for ch, chunks in all_chapter_chunks:
                    if self._stop:
                        break

                    title = getattr(ch, 'title', 'Chapter')
                    number = getattr(ch, 'number', 0)
                    safe_title = "".join(
                        c for c in title if c.isalnum() or c in " -_"
                    ).strip()
                    filepath = out_dir / f"{number:03d}_{safe_title}.wav"
                    sample_rate = 24000
                    file_started = False

                    # Speak chapter header for multi-chapter exports
                    if multi_chapter:
                        chunk_idx += 1
                        self.progress.emit(
                            f"Ch{number} '{title}' — header",
                            chunk_idx, total_chunks)
                        header_text = f"Chapter {number}. {title}."
                        audio, sr = self._generate_audio(header_text)
                        if audio is not None:
                            sample_rate = sr
                            sf.write(str(filepath), audio, sample_rate)
                            file_started = True
                            # Brief pause after header
                            silence = np.zeros(int(sample_rate * 1.5),
                                               dtype=np.float32)
                            self._append_wav(filepath, silence, sample_rate, sf)

                    # Speak each text chunk, appending to file
                    for i, chunk in enumerate(chunks):
                        if self._stop:
                            break
                        chunk_idx += 1
                        self.progress.emit(
                            f"Ch{number} '{title}' — chunk {i+1}/{len(chunks)}",
                            chunk_idx, total_chunks)

                        text_to_speak = chunk
                        print(f"[AudioExport] Ch{number} chunk {i+1}/{len(chunks)}: "
                              f"{len(text_to_speak)} chars, "
                              f"starts: {repr(text_to_speak[:80])}")

                        if self.format_with_llm:
                            text_to_speak = self._format_for_speech(text_to_speak)

                        audio, sr = self._generate_audio(text_to_speak)
                        if audio is not None:
                            duration = len(audio) / sr
                            print(f"[AudioExport] Ch{number} chunk {i+1}: "
                                  f"got {duration:.1f}s audio ({len(audio)} samples)")
                            sample_rate = sr
                            if not file_started:
                                sf.write(str(filepath), audio, sample_rate)
                                file_started = True
                            else:
                                self._append_wav(filepath, audio,
                                                 sample_rate, sf)
                        else:
                            print(f"[AudioExport] Ch{number} chunk {i+1}: "
                                  f"NO AUDIO RETURNED")

                    if file_started and not self._stop:
                        # Log final file size
                        info = sf.info(str(filepath))
                        print(f"[AudioExport] Ch{number} done: "
                              f"{info.duration:.1f}s total in {filepath.name}")
                        files_created += 1

            else:
                # ── Single-file book export ──
                filepath = out_dir / "full_book.wav"
                sample_rate = 24000
                file_started = False

                for ch_i, (ch, chunks) in enumerate(all_chapter_chunks):
                    if self._stop:
                        break
                    title = getattr(ch, 'title', 'Chapter')
                    number = getattr(ch, 'number', 0)

                    # Chapter silence separator (after the first chapter)
                    if file_started:
                        silence = np.zeros(sample_rate, dtype=np.float32)
                        self._append_wav(filepath, silence, sample_rate, sf)

                    # Speak chapter header for multi-chapter exports
                    if multi_chapter:
                        chunk_idx += 1
                        self.progress.emit(
                            f"Ch{number} '{title}' — header",
                            chunk_idx, total_chunks)
                        header_text = f"Chapter {number}. {title}."
                        audio, sr = self._generate_audio(header_text)
                        if audio is not None:
                            sample_rate = sr
                            if not file_started:
                                sf.write(str(filepath), audio, sample_rate)
                                file_started = True
                            else:
                                self._append_wav(filepath, audio,
                                                 sample_rate, sf)
                            # Brief pause after header
                            silence = np.zeros(int(sample_rate * 1.5),
                                               dtype=np.float32)
                            self._append_wav(filepath, silence, sample_rate, sf)

                    # Speak each text chunk, appending to file
                    for i, chunk in enumerate(chunks):
                        if self._stop:
                            break
                        chunk_idx += 1
                        self.progress.emit(
                            f"Ch{number} '{title}' — chunk {i+1}/{len(chunks)}",
                            chunk_idx, total_chunks)

                        text_to_speak = chunk
                        print(f"[AudioExport] Ch{number} chunk {i+1}/{len(chunks)}: "
                              f"{len(text_to_speak)} chars, "
                              f"starts: {repr(text_to_speak[:80])}")

                        if self.format_with_llm:
                            text_to_speak = self._format_for_speech(text_to_speak)

                        audio, sr = self._generate_audio(text_to_speak)
                        if audio is not None:
                            duration = len(audio) / sr
                            print(f"[AudioExport] Ch{number} chunk {i+1}: "
                                  f"got {duration:.1f}s audio ({len(audio)} samples)")
                            sample_rate = sr
                            if not file_started:
                                sf.write(str(filepath), audio, sample_rate)
                                file_started = True
                            else:
                                self._append_wav(filepath, audio,
                                                 sample_rate, sf)
                        else:
                            print(f"[AudioExport] Ch{number} chunk {i+1}: "
                                  f"NO AUDIO RETURNED")

                if file_started and not self._stop:
                    info = sf.info(str(filepath))
                    print(f"[AudioExport] Book done: "
                          f"{info.duration:.1f}s total in {filepath.name}")
                    files_created = 1

            self.finished.emit(files_created)

        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _append_wav(filepath: Path, audio: np.ndarray, sample_rate: int, sf):
        """Append audio data to an existing WAV file."""
        with sf.SoundFile(str(filepath), mode='r+') as f:
            f.seek(0, sf.SEEK_END)
            f.write(audio)

    def _format_for_speech(self, text: str) -> str:
        """Use the LLM to format text for natural speech output.

        Creates an LLMClient the same way ChatWorker does (via settings)
        to safely share the MLXModelCache without Metal threading issues.
        """
        try:
            from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
            from src.services.ai_config_service import get_ai_config

            ai_config = get_ai_config()
            settings = ai_config.get_settings()

            prefer_local = settings.get("prefer_local_model", False)
            enable_local = settings.get("enable_local_models", False)
            local_model_id = settings.get("local_model_id", "")

            if prefer_local and enable_local and local_model_id:
                is_mlx = "mlx" in local_model_id.lower()
                hf_config = HuggingFaceConfig(
                    model_id=local_model_id,
                    use_local=True,
                    device=settings.get("local_model_device", "auto"),
                    quantization=settings.get("local_model_quantization", "none") if settings.get("local_model_quantization") != "none" else None,
                    trust_remote_code=settings.get("local_model_trust_remote_code", False)
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
                    "gemini": LLMProvider.GEMINI
                }
                provider = provider_map.get(default_provider, LLMProvider.CLAUDE)
                llm = LLMClient(
                    provider=provider,
                    api_key=api_key,
                    model=ai_config.get_model(default_provider)
                )

            system = "You reformat text for speech. Output only the reformatted text, nothing else."
            prompt = (
                "Reformat the following text for text-to-speech output. "
                "Expand abbreviations (Dr. -> Doctor, Mr. -> Mister, etc.), "
                "spell out numbers (42 -> forty-two), remove markdown formatting. "
                "Do NOT change the meaning, remove content, summarize, or add content. "
                "Output ONLY the complete reformatted text.\n\n"
                f"{text}"
            )
            # max_tokens must be generous — reformatted text is at least as long
            formatted = llm.generate_text(prompt=prompt, system_prompt=system,
                                          max_tokens=max(len(text), 2000),
                                          temperature=0.1)
            return formatted if formatted else text
        except Exception:
            return text

    def _generate_audio(self, text: str):
        """Generate audio for a text chunk. Returns (numpy_array, sample_rate)."""
        if not text.strip():
            return None, 24000

        if self.engine == "kokoro":
            return self._gen_kokoro(text)
        elif self.engine == "chatterbox":
            return self._gen_chatterbox(text)
        elif self.engine == "edge":
            return self._gen_edge(text)
        elif self.engine == "system":
            return self._gen_system(text)
        return None, 24000

    def _gen_kokoro(self, text: str):
        from kokoro_onnx import Kokoro
        model_dir = Path.home() / ".writer_platform" / "kokoro"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / "kokoro-v1.0.onnx"
        voices_path = model_dir / "voices-v1.0.bin"

        if not model_path.exists() or not voices_path.exists():
            import requests
            base_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
            self.progress.emit("Downloading Kokoro model...", 0, 1)
            if not model_path.exists():
                r = requests.get(f"{base_url}/kokoro-v1.0.onnx", stream=True)
                r.raise_for_status()
                with open(model_path, 'wb') as f:
                    for data in r.iter_content(chunk_size=8192):
                        f.write(data)
            if not voices_path.exists():
                r = requests.get(f"{base_url}/voices-v1.0.bin", stream=True)
                r.raise_for_status()
                with open(voices_path, 'wb') as f:
                    for data in r.iter_content(chunk_size=8192):
                        f.write(data)

        if not hasattr(self, '_kokoro') or self._kokoro is None:
            self._kokoro = Kokoro(str(model_path), str(voices_path))

        voice = self.voice or "af_heart"
        samples, sr = self._kokoro.create(text, voice=voice, speed=1.0)
        return samples, sr

    def _gen_chatterbox(self, text: str):
        if not hasattr(self, '_chatterbox') or self._chatterbox is None:
            from mlx_audio.tts.utils import load_model
            self._chatterbox = load_model("mlx-community/chatterbox-turbo-fp16")

        gen_kwargs = {"text": text, "stream": False}
        if self.voice and self.voice != "default" and Path(self.voice).is_file():
            gen_kwargs["ref_audio"] = self.voice

        results = list(self._chatterbox.generate(**gen_kwargs))
        if not results:
            return None, 24000

        audio = results[0].audio
        if hasattr(audio, 'numpy'):
            audio = audio.numpy()
        audio = np.array(audio).flatten().astype(np.float32)
        sr = getattr(self._chatterbox, 'sample_rate', 24000)
        return audio, sr

    def _gen_edge(self, text: str):
        import asyncio
        import edge_tts
        import tempfile
        import soundfile as sf
        import os

        voice = self.voice or "en-US-AvaMultilingualNeural"
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()

        async def _gen():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(tmp.name)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_gen())
        loop.close()

        try:
            audio, sr = sf.read(tmp.name)
            return audio.astype(np.float32), sr
        except Exception:
            try:
                from pydub import AudioSegment
                seg = AudioSegment.from_mp3(tmp.name)
                samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
                samples = samples / (2**15)
                return samples, seg.frame_rate
            except ImportError:
                import subprocess
                wav_path = tmp.name.replace('.mp3', '.wav')
                subprocess.run(['ffmpeg', '-i', tmp.name, '-y', wav_path],
                               capture_output=True)
                audio, sr = sf.read(wav_path)
                os.unlink(wav_path)
                return audio.astype(np.float32), sr
        finally:
            os.unlink(tmp.name)

    def _gen_system(self, text: str):
        import subprocess
        import platform
        import tempfile
        import soundfile as sf
        import os

        if platform.system() != "Darwin":
            raise RuntimeError("System TTS export only on macOS. Use Kokoro or Edge.")

        tmp = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False)
        tmp.close()
        wav_path = tmp.name.replace('.aiff', '.wav')

        subprocess.run(['say', '-o', tmp.name, text], capture_output=True)
        subprocess.run(['afconvert', '-f', 'WAVE', '-d', 'LEI16',
                       tmp.name, wav_path], capture_output=True)

        audio, sr = sf.read(wav_path)
        os.unlink(tmp.name)
        os.unlink(wav_path)
        return audio.astype(np.float32), sr


# ── Dialog ───────────────────────────────────────────────────────

class ExportAudioDialog(QDialog):
    """Dialog for exporting chapters as audio files."""

    def __init__(self, chapters: list, current_chapter_idx: int = -1, parent=None):
        super().__init__(parent)
        self.chapters = chapters
        self.current_chapter_idx = current_chapter_idx
        self._worker: Optional[_ExportWorker] = None
        self._tts_service = None
        self._init_ui()

    def _get_tts_service(self):
        """Get or create a TTS service for voice listings."""
        if self._tts_service is None:
            try:
                from src.services.tts_service import TTSService
                self._tts_service = TTSService()
            except Exception:
                pass
        return self._tts_service

    def _load_tts_settings(self) -> dict:
        """Load saved TTS settings so the export dialog matches the user's config."""
        try:
            from src.services.ai_config_service import get_ai_config
            return get_ai_config().get_settings()
        except Exception:
            return {}

    def _init_ui(self):
        self.setWindowTitle("Export Audio Book")
        self.setMinimumWidth(520)
        self.resize(560, 600)

        layout = QVBoxLayout(self)
        saved = self._load_tts_settings()

        # Engine + voice
        engine_group = QGroupBox("Voice Engine")
        engine_layout = QFormLayout()

        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Kokoro - High Quality (Local, 82M)", "kokoro")
        self.engine_combo.addItem("Chatterbox Turbo - Neural (Local, 350M)", "chatterbox")
        self.engine_combo.addItem("Edge TTS - Microsoft Neural (Online)", "edge")
        self.engine_combo.addItem("System TTS (macOS only)", "system")
        # Pre-select saved engine
        saved_engine = saved.get("tts_engine", "kokoro")
        for i in range(self.engine_combo.count()):
            if self.engine_combo.itemData(i) == saved_engine:
                self.engine_combo.setCurrentIndex(i)
                break
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        engine_layout.addRow("Engine:", self.engine_combo)

        self.genre_combo = QComboBox()
        self.genre_combo.addItem("Custom (pick voice below)", "")
        try:
            from src.services.tts_service import NARRATIVE_GENRES
            for key, info in NARRATIVE_GENRES.items():
                self.genre_combo.addItem(
                    f"{info['label']} — {info['description']}", key)
        except Exception:
            pass
        # Pre-select saved genre
        saved_genre = saved.get("tts_genre", "")
        for i in range(self.genre_combo.count()):
            if self.genre_combo.itemData(i) == saved_genre:
                self.genre_combo.setCurrentIndex(i)
                break
        self.genre_combo.currentIndexChanged.connect(self._on_genre_changed)
        engine_layout.addRow("Narrative Style:", self.genre_combo)

        self.voice_combo = QComboBox()
        self._populate_voices()
        # Pre-select saved voice
        saved_voice = saved.get("tts_voice", "")
        if saved_voice:
            for i in range(self.voice_combo.count()):
                if self.voice_combo.itemData(i) == saved_voice:
                    self.voice_combo.setCurrentIndex(i)
                    break
        engine_layout.addRow("Voice:", self.voice_combo)

        engine_group.setLayout(engine_layout)
        layout.addWidget(engine_group)

        # Chapter selection
        chapter_group = QGroupBox("Chapters to Export")
        chapter_layout = QVBoxLayout()

        self.scope_group = QButtonGroup(self)

        self.current_radio = QRadioButton("Current chapter only")
        self.current_radio.setChecked(True)
        if self.current_chapter_idx < 0:
            self.current_radio.setEnabled(False)
            self.current_radio.setChecked(False)
        self.scope_group.addButton(self.current_radio, 0)
        chapter_layout.addWidget(self.current_radio)

        self.selected_radio = QRadioButton("Selected chapters:")
        self.scope_group.addButton(self.selected_radio, 1)
        chapter_layout.addWidget(self.selected_radio)

        self.chapter_list = QListWidget()
        self.chapter_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.chapter_list.setMaximumHeight(120)
        for ch in self.chapters:
            item = QListWidgetItem(f"{ch.number}. {ch.title}")
            item.setData(Qt.ItemDataRole.UserRole, ch.id)
            self.chapter_list.addItem(item)
        chapter_layout.addWidget(self.chapter_list)

        self.all_radio = QRadioButton("Entire book")
        if self.current_chapter_idx < 0:
            self.all_radio.setChecked(True)
        self.scope_group.addButton(self.all_radio, 2)
        chapter_layout.addWidget(self.all_radio)

        chapter_group.setLayout(chapter_layout)
        layout.addWidget(chapter_group)

        # Output options
        options_group = QGroupBox("Output Options")
        options_layout = QVBoxLayout()

        self.per_chapter_cb = QCheckBox("Export as separate files per chapter")
        self.per_chapter_cb.setChecked(True)
        self.per_chapter_cb.setToolTip(
            "Checked: one WAV per chapter (001_Title.wav, 002_Title.wav...)\n"
            "Unchecked: one WAV for all selected chapters (full_book.wav)"
        )
        options_layout.addWidget(self.per_chapter_cb)

        self.format_cb = QCheckBox("Format text for speech (expand abbreviations, add pauses)")
        self.format_cb.setToolTip(
            "Uses the local AI model to reformat text for natural speech.\n"
            "Expands abbreviations, spells out numbers, adds breathing pauses.\n"
            "Slower but produces more natural results."
        )
        options_layout.addWidget(self.format_cb)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Output folder
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Output:"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setText(str(Path.home() / "Desktop" / "AudioBook"))
        folder_layout.addWidget(self.folder_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        folder_layout.addWidget(browse_btn)
        layout.addLayout(folder_layout)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.export_btn = QPushButton("Export")
        self.export_btn.setStyleSheet("font-weight: bold; padding: 6px 20px;")
        self.export_btn.clicked.connect(self._export)
        btn_layout.addWidget(self.export_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._cancel)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _populate_voices(self):
        """Populate voice combo from the TTS service's actual voice list."""
        self.voice_combo.clear()
        engine_key = self.engine_combo.currentData()

        # Try to get voices from the TTS service (single source of truth)
        svc = self._get_tts_service()
        if svc:
            try:
                from src.services.tts_service import TTSEngine
                engine_map = {
                    "kokoro": TTSEngine.KOKORO,
                    "chatterbox": TTSEngine.CHATTERBOX,
                    "edge": TTSEngine.EDGE,
                    "system": TTSEngine.SYSTEM,
                    "vibevoice": TTSEngine.VIBEVOICE,
                }
                engine_enum = engine_map.get(engine_key)
                if engine_enum:
                    voices = svc.get_voices(engine_enum)
                    if voices:
                        for v in voices:
                            self.voice_combo.addItem(v.name, v.id)
                        return
            except Exception:
                pass

        # Fallback: hardcoded voices if TTS service unavailable
        if engine_key == "kokoro":
            voices = [
                ("af_heart", "Heart (warm)"), ("af_bella", "Bella (clear)"),
                ("af_sarah", "Sarah (calm)"), ("af_nova", "Nova (energetic)"),
                ("am_adam", "Adam (deep)"), ("am_michael", "Michael (clear)"),
                ("bf_emma", "Emma (British)"), ("bm_george", "George (British)"),
            ]
        elif engine_key == "edge":
            voices = [
                ("en-US-AvaMultilingualNeural", "Ava (US, warm)"),
                ("en-US-AndrewMultilingualNeural", "Andrew (US, calm)"),
                ("en-US-AriaNeural", "Aria (US, expressive)"),
                ("en-US-GuyNeural", "Guy (US, conversational)"),
                ("en-GB-SoniaNeural", "Sonia (UK, refined)"),
                ("en-GB-RyanNeural", "Ryan (UK, articulate)"),
            ]
        elif engine_key == "chatterbox":
            voices = [("default", "Default (Neural)")]
        else:
            voices = [("default", "System Default")]
        for vid, vname in voices:
            self.voice_combo.addItem(vname, vid)

    def _on_engine_changed(self, index):
        self._populate_voices()
        # Re-apply genre selection if one is active
        self._on_genre_changed(self.genre_combo.currentIndex())

    def _on_genre_changed(self, index):
        """When a narrative genre is selected, auto-pick the best voice."""
        genre_key = self.genre_combo.currentData()
        if not genre_key:
            return  # "Custom" selected — leave voice combo alone

        engine_key = self.engine_combo.currentData()
        try:
            from src.services.tts_service import get_genre_voice
            voice_id = get_genre_voice(genre_key, engine_key)
            if voice_id:
                for i in range(self.voice_combo.count()):
                    if self.voice_combo.itemData(i) == voice_id:
                        self.voice_combo.setCurrentIndex(i)
                        return
        except Exception:
            pass

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.folder_edit.setText(folder)

    def _get_selected_chapters(self) -> list:
        scope = self.scope_group.checkedId()
        if scope == 0:
            if 0 <= self.current_chapter_idx < len(self.chapters):
                return [self.chapters[self.current_chapter_idx]]
            return []
        elif scope == 1:
            selected = []
            for item in self.chapter_list.selectedItems():
                ch_id = item.data(Qt.ItemDataRole.UserRole)
                ch = next((c for c in self.chapters if c.id == ch_id), None)
                if ch:
                    selected.append(ch)
            return selected
        else:
            return list(self.chapters)

    def _export(self):
        chapters = self._get_selected_chapters()
        if not chapters:
            QMessageBox.warning(self, "No Chapters", "Select at least one chapter.")
            return
        folder = self.folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "No Folder", "Select an output folder.")
            return

        # Sort chapters by number to ensure correct order
        chapters = sorted(chapters, key=lambda c: getattr(c, 'number', 0))

        # Find project directory for loading content from disk
        project_dir = None
        try:
            p = self.parent()
            while p:
                if hasattr(p, 'current_project') and p.current_project:
                    project_dir = Path(p.current_project.project_path).parent
                    break
                p = p.parent() if hasattr(p, 'parent') and callable(p.parent) else None
        except Exception:
            pass

        # Load content from disk for all chapters
        for ch in chapters:
            if not getattr(ch, 'content', '') and project_dir:
                try:
                    ch.load_content_from_file(project_dir)
                except Exception:
                    pass

        # Warn about chapters with no content
        empty = [f"Ch{getattr(ch, 'number', '?')}: {getattr(ch, 'title', '?')}"
                 for ch in chapters if not getattr(ch, 'content', '')]
        if empty:
            msg = "The following chapters have no content and will be skipped:\n\n"
            msg += "\n".join(empty)
            QMessageBox.warning(self, "Missing Content", msg)

        # Check required dependency before starting
        try:
            import soundfile  # noqa: F401
        except ImportError:
            QMessageBox.warning(
                self, "Missing Dependency",
                "The 'soundfile' package is required for audio export.\n\n"
                "Install it with:\n  pip install soundfile"
            )
            return

        self.export_btn.setEnabled(False)
        self.export_btn.setText("Exporting...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)

        self._worker = _ExportWorker(
            chapters=chapters,
            engine=self.engine_combo.currentData(),
            voice=self.voice_combo.currentData(),
            output_dir=folder,
            per_chapter=self.per_chapter_cb.isChecked(),
            format_with_llm=self.format_cb.isChecked(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(timeout=5000)
        self.reject()

    def _on_progress(self, msg, current, total):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        self.progress_label.setText(msg)

    def _on_finished(self, count):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.export_btn.setEnabled(True)
        self.export_btn.setText("Export")
        QMessageBox.information(
            self, "Export Complete",
            f"Exported {count} file(s) to:\n{self.folder_edit.text()}"
        )
        self.accept()

    def _on_error(self, msg):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.export_btn.setEnabled(True)
        self.export_btn.setText("Export")
        QMessageBox.warning(self, "Export Failed", msg)
