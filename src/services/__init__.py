"""Services for Writer Platform."""

from .tts_service import TTSService, TTSVoice, TTSEngine, get_tts_service
from .tts_document_generator import (
    TTSDocumentGenerator,
    TTSDocumentConfig,
    TTSFormat,
    SpeakerConfig,
    create_default_config,
    get_tts_output_dir
)

__all__ = [
    'TTSService', 'TTSVoice', 'TTSEngine', 'get_tts_service',
    'TTSDocumentGenerator', 'TTSDocumentConfig', 'TTSFormat', 'SpeakerConfig',
    'create_default_config', 'get_tts_output_dir'
]
