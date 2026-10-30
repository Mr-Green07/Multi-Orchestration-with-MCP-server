# pyrefly: ignore [missing-import]
from src.utils.exceptions import AppError

class ResponseGenerationError(AppError):
    """
    Base exception for the LLM response generation layer.
    Fires when the assistant fails to generate a verbal reply.
    """
    pass

class LLMTimeoutError(ResponseGenerationError):
    """
    Raised when the connection to the local LLM (Ollama / llama.cpp) 
    takes too long to respond.
    
    This is critical because in a voice assistant, if the LLM hangs for 30 seconds,
    the user will think the assistant is broken. We catch this to immediately
    trigger a fallback "I'm having trouble thinking right now" TTS response.
    """
    pass
