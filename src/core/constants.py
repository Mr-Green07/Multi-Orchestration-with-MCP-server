"""
Global constants for the ASR Assistant.
These values act as system-wide defaults and "magic numbers". 
While config.yaml and .env allow user customization, these constants 
ensure the system always has a safe fallback to operate.
"""

from pathlib import Path

# ---------------------------------------------------------
# File System Paths
# ---------------------------------------------------------
ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
MODELS_DIR = ROOT_DIR / "offline_models"
SCRIPTS_MODELS_DIR = ROOT_DIR / "scripts" / "models"

# ---------------------------------------------------------
# Audio & Signal Processing
# ---------------------------------------------------------
# Speech-to-text models (Whisper/Silero) strictly require 16 kHz mono.
AUDIO_SAMPLE_RATE_STT = 16000 
AUDIO_CHANNELS = 1

# Piper TTS uses 22050 Hz by default
AUDIO_SAMPLE_RATE_TTS = 22050 

# Frame processing size in milliseconds
DEFAULT_FRAME_MS = 30

# ---------------------------------------------------------
# Models (Fallbacks if not in config.yaml / .env)
# ---------------------------------------------------------
# STT (Whisper)
DEFAULT_WHISPER_MODEL = "base"
DEFAULT_WHISPER_LANG = "en"

# VAD (Silero)
VAD_MODEL_PATH = SCRIPTS_MODELS_DIR / "silero_vad.onnx"

# LLM (Ollama)
DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_LLM_MODEL = "gemma4:e2b-it-qat"
DEFAULT_LLM_URL = "http://localhost:11434"

# ---------------------------------------------------------
# Event Bus Topics / System States
# ---------------------------------------------------------
# (Strings used when passing events between audio thread and main loop)
EVENT_WAKE = "wake"
EVENT_BARGE_IN = "barge_in"
EVENT_SPEECH_START = "speech_start"
EVENT_ENDPOINT = "endpoint"
EVENT_TIMEOUT = "timeout"

# ---------------------------------------------------------
# API & Network
# ---------------------------------------------------------
DEFAULT_API_PORT = 8000
MAX_UPLOAD_SIZE_MB = 500
SUPPORTED_AUDIO_FORMATS = [".wav", ".mp3", ".ogg", ".flac", ".m4a", ".webm"]
