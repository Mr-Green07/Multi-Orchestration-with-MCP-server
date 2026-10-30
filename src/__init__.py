"""
Voice Assistant Package

A comprehensive voice assistant system that integrates:
- Automatic Speech Recognition (ASR) for audio transcription
- Audio processing and voice activity detection
- Natural Language Understanding (NLU)
- Text-to-Speech (TTS) for voice responses
- Task execution and orchestration
- Wake word detection for hands-free activation

This package provides a complete pipeline for building voice-activated
applications with support for multiple languages and custom configurations.

Modules:
    asr: Automatic Speech Recognition (ASR) using OpenAI Whisper
    audio: Audio input/output handling, buffering, and voice activity detection
    core: Core configuration, constants, and orchestration
    nlu: Natural Language Understanding and intent detection
    response_generation: Generate responses based on intent
    storage: Data persistence and caching
    tasks: Task definitions and execution
    tts: Text-to-Speech synthesis
    utils: Utility functions and helpers
    wake_word: Wake word detection for voice activation
    api: REST API and external interfaces

Version:
    1.0.0 (May 2026)

Example:
    >>> from voice_assistant import VoiceAssistant, Config
    >>> config = Config.from_file("config.yaml")
    >>> assistant = VoiceAssistant(config)
    >>> result = assistant.process_audio("hello.wav")
    >>> print(f"Transcribed: {result.text}")
    >>> print(f"Intent: {result.intent}")
"""

import logging
from typing import Optional
from pathlib import Path

# Version information
__version__ = "1.0.0"
__author__ = "Voice Assistant Team"
__license__ = "MIT"

# Configure package-level logging
logging.getLogger(__name__).addHandler(logging.NullHandler())

logger = logging.getLogger(__name__)


# Lazy imports for main components
def __getattr__(name: str):
    """
    Lazy load modules and classes to avoid circular imports.
    
    Supports importing main components directly from voice_assistant:
    - VoiceAssistant: Main orchestrator class
    - Config: Configuration management
    - ASRProcessor: Audio processing for ASR
    - Transcriber: Speech-to-text transcription
    - WakeWordDetector: Wake word detection
    - TextToSpeech: Speech synthesis
    
    Args:
        name (str): Name of the requested attribute
        
    Returns:
        The requested module or class
        
    Raises:
        AttributeError: If the requested attribute doesn't exist
    """
    
    # Core orchestration
    if name == "VoiceAssistant":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.core.orchestrator import VoiceAssistant
        return VoiceAssistant
    
    # Configuration management
    if name == "Config":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.core.config import Config
        return Config
    
    # Constants
    if name == "Constants":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.core.constants import Constants
        return Constants
    
    # ASR components
    if name == "ASRProcessor":
        # pyrefly: ignore [missing-import]
        from voice_assistant.asr.processor import ASRProcessor
        return ASRProcessor
    
    if name == "Transcriber":
        # pyrefly: ignore [missing-import]
        from voice_assistant.asr.transcriber import Transcriber
        return Transcriber
    
    if name == "WhisperModel":
        # pyrefly: ignore [missing-import]
        from voice_assistant.asr.transcriber import WhisperModel
        return WhisperModel
    
    if name == "TranscriptionResult":
        # pyrefly: ignore [missing-import]
        from voice_assistant.asr.transcriber import TranscriptionResult
        return TranscriptionResult
    
    # ASR exceptions
    if name == "ASRException":
        # pyrefly: ignore [missing-import]
        from voice_assistant.asr.exceptions import ASRException
        return ASRException
    
    # Audio components
    if name == "AudioProcessor":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.audio.audio_processor import AudioProcessor
        return AudioProcessor
    
    if name == "VoiceActivityDetector":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.audio.vad import VoiceActivityDetector
        return VoiceActivityDetector
    
    if name == "AudioBufferManager":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.audio.buffer_manager import AudioBufferManager
        return AudioBufferManager
    
    if name == "AudioInputHandler":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.audio.input_handler import AudioInputHandler
        return AudioInputHandler
    
    if name == "AudioOutputHandler":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.audio.output_handler import AudioOutputHandler
        return AudioOutputHandler
    
    if name == "AudioException":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.audio.exceptions import AudioException
        return AudioException
    
    # Wake word detection
    if name == "WakeWordDetector":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.wake_word.detector import WakeWordDetector
        return WakeWordDetector
    
    # NLU components
    if name == "NLUProcessor":
        # pyrefly: ignore [missing-import]
        from voice_assistant.nlu.processor import NLUProcessor
        return NLUProcessor
    
    # TTS components
    if name == "TextToSpeech":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.tts.synthesizer import TextToSpeech
        return TextToSpeech
    
    # Response generation
    if name == "ResponseGenerator":
        # pyrefly: ignore [missing-import]
        from voice_assistant.response_generation.generator import ResponseGenerator
        return ResponseGenerator
    
    # Storage components
    if name == "StorageManager":
        # pyrefly: ignore [missing-import]
        from voice_assistant.storage.manager import StorageManager
        return StorageManager
    
    # Task components
    if name == "TaskExecutor":
        # pyrefly: ignore [missing-import, missing-module-attribute]
        from voice_assistant.tasks.executor import TaskExecutor
        return TaskExecutor
    
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    # Version and metadata
    "__version__",
    "__author__",
    "__license__",
    
    # Core components
    "VoiceAssistant",
    "Config",
    "Constants",
    
    # ASR components
    "ASRProcessor",
    "Transcriber",
    "WhisperModel",
    "TranscriptionResult",
    "ASRException",
    
    # Audio components
    "AudioProcessor",
    "VoiceActivityDetector",
    "AudioBufferManager",
    "AudioInputHandler",
    "AudioOutputHandler",
    "AudioException",
    
    # Wake word detection
    "WakeWordDetector",
    
    # NLU components
    "NLUProcessor",
    
    # TTS components
    "TextToSpeech",
    
    # Response generation
    "ResponseGenerator",
    
    # Storage
    "StorageManager",
    
    # Task execution
    "TaskExecutor",
]


def get_version() -> str:
    """
    Get the version of the voice_assistant package.
    
    Returns:
        str: Version string (e.g., "1.0.0")
        
    Example:
        >>> from voice_assistant import get_version
        >>> print(get_version())
        1.0.0
    """
    return __version__


def get_package_info() -> dict:
    """
    Get comprehensive package information.
    
    Returns:
        dict: Dictionary containing version, author, license, and package path
        
    Example:
        >>> from voice_assistant import get_package_info
        >>> info = get_package_info()
        >>> print(info["version"])
        1.0.0
    """
    return {
        "name": "voice_assistant",
        "version": __version__,
        "author": __author__,
        "license": __license__,
        "path": str(Path(__file__).parent),
        "description": __doc__,
    }


# Package initialization
logger.debug(f"Voice Assistant package {__version__} loaded successfully")
