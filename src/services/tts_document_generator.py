"""TTS Document Generator - Creates formatted text files for TTS engines."""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


class TTSFormat(Enum):
    """Supported TTS document formats."""
    VIBEVOICE = "vibevoice"  # Speaker N: [text]
    PLAIN = "plain"  # Plain text, no speaker labels
    SSML = "ssml"  # SSML markup for advanced TTS


@dataclass
class SpeakerConfig:
    """Configuration for a TTS speaker/voice."""
    speaker_id: int  # 1-based speaker number
    name: str  # Display name (e.g., "Narrator", "Alice")
    voice_id: str  # Voice ID for TTS engine
    description: str = ""  # Optional description


@dataclass
class TTSDocumentConfig:
    """Configuration for TTS document generation."""
    format: TTSFormat = TTSFormat.VIBEVOICE
    speakers: List[SpeakerConfig] = field(default_factory=list)
    default_speaker: int = 1  # Default speaker ID for unmarked text
    narrator_speaker: int = 1  # Speaker ID for narrative/description text
    dialogue_detection: bool = True  # Auto-detect dialogue
    preserve_paragraphs: bool = True  # Keep paragraph breaks
    max_line_length: int = 500  # Split long lines for better synthesis

    def __post_init__(self):
        if not self.speakers:
            # Default single narrator
            self.speakers = [
                SpeakerConfig(1, "Narrator", "emma", "Default narrator voice")
            ]


class TTSDocumentGenerator:
    """Generates TTS-formatted documents from chapter text."""

    # Dialogue patterns
    DIALOGUE_PATTERN = re.compile(
        r'"([^"]+)"'  # Quoted dialogue
        r'|'
        r'"([^"]+)"'  # Smart quotes
        r'|'
        r"'([^']+)'"  # Single quotes (less common for dialogue)
    )

    # Speaker attribution patterns (he said, she asked, etc.)
    ATTRIBUTION_PATTERN = re.compile(
        r',?\s*(?:said|asked|replied|answered|exclaimed|whispered|shouted|muttered|'
        r'murmured|called|cried|yelled|screamed|demanded|inquired|stated|declared|'
        r'announced|responded|remarked|commented|added|continued|explained|noted|'
        r'observed|suggested|wondered|thought)\s+(\w+)',
        re.IGNORECASE
    )

    # Character name pattern (for tracking speakers in dialogue)
    NAME_PATTERN = re.compile(r'\b([A-Z][a-z]+)\b')

    def __init__(self, config: Optional[TTSDocumentConfig] = None):
        """Initialize generator with configuration."""
        self.config = config or TTSDocumentConfig()
        self._character_to_speaker: Dict[str, int] = {}

    def generate_tts_document(
        self,
        text: str,
        output_path: Path,
        chapter_name: str = "chapter"
    ) -> Tuple[Path, List[str]]:
        """Generate a TTS document from text.

        Args:
            text: Source text to convert
            output_path: Directory to save the TTS document
            chapter_name: Name for the output file

        Returns:
            Tuple of (output file path, list of speaker names used)
        """
        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filename
        safe_name = re.sub(r'[^\w\-_]', '_', chapter_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_name}_tts.txt"
        filepath = output_path / filename

        # Process text based on format
        if self.config.format == TTSFormat.VIBEVOICE:
            content, speakers_used = self._format_vibevoice(text)
        elif self.config.format == TTSFormat.SSML:
            content, speakers_used = self._format_ssml(text)
        else:
            content, speakers_used = self._format_plain(text)

        # Write output file (overwrite if exists)
        filepath.write_text(content, encoding='utf-8')

        return filepath, speakers_used

    def _format_vibevoice(self, text: str) -> Tuple[str, List[str]]:
        """Format text for VibeVoice (Speaker N: [text] format).

        Returns:
            Tuple of (formatted content, list of speaker names)
        """
        lines = []
        speakers_used = set()
        current_speaker = self.config.narrator_speaker

        # Split into paragraphs
        paragraphs = self._split_paragraphs(text)

        for para in paragraphs:
            if not para.strip():
                continue

            # Check if this is dialogue
            if self.config.dialogue_detection:
                processed_lines = self._process_paragraph_with_dialogue(para)
                for speaker_id, line_text in processed_lines:
                    if line_text.strip():
                        speaker = self._get_speaker(speaker_id)
                        speakers_used.add(speaker.name)
                        lines.append(f"Speaker {speaker_id}: {line_text.strip()}")
            else:
                # No dialogue detection, use default speaker
                speaker = self._get_speaker(current_speaker)
                speakers_used.add(speaker.name)
                # Split long paragraphs
                for chunk in self._split_long_text(para):
                    lines.append(f"Speaker {current_speaker}: {chunk.strip()}")

        content = "\n".join(lines)
        return content, list(speakers_used)

    def _process_paragraph_with_dialogue(self, para: str) -> List[Tuple[int, str]]:
        """Process a paragraph, detecting dialogue and narrative.

        Returns:
            List of (speaker_id, text) tuples
        """
        results = []
        narrator_id = self.config.narrator_speaker

        # Find all dialogue in the paragraph
        dialogue_matches = list(self.DIALOGUE_PATTERN.finditer(para))

        if not dialogue_matches:
            # No dialogue, all narrative
            for chunk in self._split_long_text(para):
                results.append((narrator_id, chunk))
            return results

        # Process text with dialogue
        last_end = 0
        dialogue_speaker = self._get_next_dialogue_speaker()

        for match in dialogue_matches:
            # Add narrative text before dialogue
            before_text = para[last_end:match.start()].strip()
            if before_text:
                # Check for speaker attribution in the preceding text
                attr_match = self.ATTRIBUTION_PATTERN.search(before_text)
                if attr_match:
                    character_name = attr_match.group(1)
                    dialogue_speaker = self._get_speaker_for_character(character_name)

                for chunk in self._split_long_text(before_text):
                    results.append((narrator_id, chunk))

            # Add the dialogue
            dialogue_text = match.group(1) or match.group(2) or match.group(3)
            if dialogue_text:
                for chunk in self._split_long_text(dialogue_text):
                    results.append((dialogue_speaker, chunk))

            # Check for speaker attribution after dialogue
            after_start = match.end()
            after_text = para[after_start:after_start + 100]  # Look ahead
            attr_match = self.ATTRIBUTION_PATTERN.search(after_text)
            if attr_match:
                character_name = attr_match.group(1)
                # Update speaker mapping for next dialogue
                self._character_to_speaker[character_name.lower()] = dialogue_speaker

            # Alternate speakers for next dialogue
            dialogue_speaker = self._get_next_dialogue_speaker(dialogue_speaker)
            last_end = match.end()

        # Add remaining narrative
        remaining = para[last_end:].strip()
        if remaining:
            for chunk in self._split_long_text(remaining):
                results.append((narrator_id, chunk))

        return results

    def _get_speaker(self, speaker_id: int) -> SpeakerConfig:
        """Get speaker config by ID."""
        for speaker in self.config.speakers:
            if speaker.speaker_id == speaker_id:
                return speaker
        # Return first speaker as fallback
        return self.config.speakers[0]

    def _get_next_dialogue_speaker(self, current: int = None) -> int:
        """Get the next dialogue speaker ID (alternating)."""
        dialogue_speakers = [s.speaker_id for s in self.config.speakers
                          if s.speaker_id != self.config.narrator_speaker]
        if not dialogue_speakers:
            # If only narrator, use narrator for dialogue too
            return self.config.narrator_speaker

        if current is None:
            return dialogue_speakers[0]

        try:
            idx = dialogue_speakers.index(current)
            return dialogue_speakers[(idx + 1) % len(dialogue_speakers)]
        except ValueError:
            return dialogue_speakers[0]

    def _get_speaker_for_character(self, character_name: str) -> int:
        """Get or assign a speaker ID for a character."""
        name_lower = character_name.lower()
        if name_lower in self._character_to_speaker:
            return self._character_to_speaker[name_lower]

        # Assign next available dialogue speaker
        dialogue_speakers = [s.speaker_id for s in self.config.speakers
                          if s.speaker_id != self.config.narrator_speaker]
        if dialogue_speakers:
            # Use modulo to cycle through speakers
            idx = len(self._character_to_speaker) % len(dialogue_speakers)
            speaker_id = dialogue_speakers[idx]
            self._character_to_speaker[name_lower] = speaker_id
            return speaker_id

        return self.config.default_speaker

    def _format_plain(self, text: str) -> Tuple[str, List[str]]:
        """Format as plain text."""
        # Just clean up the text
        paragraphs = self._split_paragraphs(text)
        content = "\n\n".join(p.strip() for p in paragraphs if p.strip())
        return content, ["Default"]

    def _format_ssml(self, text: str) -> Tuple[str, List[str]]:
        """Format as SSML."""
        # Basic SSML wrapper
        paragraphs = self._split_paragraphs(text)
        ssml_parts = ['<speak>']

        for para in paragraphs:
            if para.strip():
                # Escape XML special characters
                escaped = (para
                    .replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('"', '&quot;')
                )
                ssml_parts.append(f'  <p>{escaped}</p>')

        ssml_parts.append('</speak>')
        content = "\n".join(ssml_parts)
        return content, ["Default"]

    def _split_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs."""
        # Split on double newlines or single newlines followed by indentation
        paragraphs = re.split(r'\n\s*\n|\n(?=\s{2,})', text)
        return [p.strip() for p in paragraphs]

    def _split_long_text(self, text: str) -> List[str]:
        """Split long text into manageable chunks."""
        if len(text) <= self.config.max_line_length:
            return [text]

        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text)
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 <= self.config.max_line_length:
                current_chunk += (" " if current_chunk else "") + sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [text]

    def get_speaker_names(self) -> List[str]:
        """Get list of configured speaker names for command line."""
        return [s.name for s in self.config.speakers]

    def get_speaker_voices(self) -> List[str]:
        """Get list of speaker voice IDs."""
        return [s.voice_id for s in self.config.speakers]


def create_default_config(num_speakers: int = 2) -> TTSDocumentConfig:
    """Create a default TTS configuration.

    Args:
        num_speakers: Number of speakers (1-4)

    Returns:
        TTSDocumentConfig with default speakers
    """
    default_voices = [
        ("Narrator", "emma", "Narrative and description"),
        ("Character 1", "carter", "First dialogue voice"),
        ("Character 2", "grace", "Second dialogue voice"),
        ("Character 3", "frank", "Third dialogue voice"),
    ]

    speakers = []
    for i in range(min(num_speakers, 4)):
        name, voice, desc = default_voices[i]
        speakers.append(SpeakerConfig(
            speaker_id=i + 1,
            name=name,
            voice_id=voice,
            description=desc
        ))

    return TTSDocumentConfig(
        format=TTSFormat.VIBEVOICE,
        speakers=speakers,
        default_speaker=1,
        narrator_speaker=1,
        dialogue_detection=True
    )


def get_tts_output_dir() -> Path:
    """Get the default TTS output directory."""
    tts_dir = Path.home() / ".writer_platform" / "tts_output"
    tts_dir.mkdir(parents=True, exist_ok=True)
    return tts_dir
