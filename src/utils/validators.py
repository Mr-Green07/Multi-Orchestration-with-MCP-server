import os
from pathlib import Path
from src.core.constants import SUPPORTED_AUDIO_FORMATS
from src.utils.exceptions import AppError

class ValidationError(AppError):
    """Exception raised when input validation fails."""
    pass

def validate_audio_format(filename: str | Path) -> str:
    """
    Validates that the provided audio file has a supported extension.
    
    :param filename: The name or path of the audio file.
    :return: The validated extension in lowercase (e.g., '.wav').
    :raises ValidationError: If the format is not supported.
    """
    path = Path(filename)
    ext = path.suffix.lower()
    
    if not ext:
        raise ValidationError(f"File '{path.name}' is missing an extension.")
        
    if ext not in SUPPORTED_AUDIO_FORMATS:
        raise ValidationError(
            f"Unsupported audio format '{ext}'. "
            f"Supported formats are: {', '.join(SUPPORTED_AUDIO_FORMATS)}"
        )
        
    return ext


def validate_text_length(text: str, max_chars: int = 5000, min_chars: int = 1) -> str:
    """
    Validates that a string of text falls within acceptable length bounds.
    Used before sending text to TTS (to prevent memory crashes) or the LLM.
    
    :param text: The input text.
    :param max_chars: Maximum allowed characters.
    :param min_chars: Minimum allowed characters.
    :return: The stripped, validated text.
    :raises ValidationError: If the text is too long, too short, or empty.
    """
    if text is None:
        raise ValidationError("Input text cannot be None.")
        
    cleaned_text = text.strip()
    length = len(cleaned_text)
    
    if length < min_chars:
        raise ValidationError(f"Text is too short. Minimum length is {min_chars} character(s).")
        
    if length > max_chars:
        raise ValidationError(f"Text is too long ({length} chars). Maximum allowed is {max_chars}.")
        
    return cleaned_text


def validate_language_code(language: str) -> str:
    """
    Validates that a language code is a valid 2-letter ISO-639-1 code 
    supported by Whisper.
    
    :param language: The language code (e.g., 'en', 'fr').
    :return: The validated language code in lowercase.
    :raises ValidationError: If the language code is invalid.
    """
    if not language or not isinstance(language, str):
        raise ValidationError("Language code must be a non-empty string.")
        
    cleaned = language.strip().lower()
    
    # Typical Whisper / Standard 2-letter language codes 
    # (A subset of commonly used ones to validate shape, or we just validate it's 2 chars)
    if len(cleaned) != 2 or not cleaned.isalpha():
        raise ValidationError(
            f"Invalid language code format: '{language}'. "
            "Expected a 2-letter ISO-639-1 code (e.g., 'en', 'es', 'fr')."
        )
        
    return cleaned
