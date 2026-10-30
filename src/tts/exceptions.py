from src.utils.exceptions import AppError

class TTSError(AppError):
    """
    Base exception for everything in the Text-to-Speech (TTS) layer.
    """
    pass

class SynthesisFailedError(TTSError):
    """
    Raised when the TTS engine (e.g., Piper, pyttsx3) fails to convert 
    the text string into an audio stream.
    
    Examples:
      - The text contains unsupported characters (e.g., weird emojis).
      - The TTS voice model file (.onnx) is missing or corrupted.
      - The audio device is locked by another application.
    """
    pass