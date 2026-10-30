import logging
from typing import Dict, Any, Generator

# pyrefly: ignore [missing-import]
from src.nlu.intent import Intent
# pyrefly: ignore [missing-import]
from src.llm.connector import LLMConnector
# pyrefly: ignore [missing-import]
from src.response_generation.template_engine import TemplateEngine
# pyrefly: ignore [missing-import]
from src.response_generation.formatter import TTSFormatter

logger = logging.getLogger(__name__)

class LLMResponseGenerator:
    def __init__(self):
        # Initialize the underlying components
        self.template_engine = TemplateEngine()
        self.connector = LLMConnector() # Defaults to gemma model locally

    def generate_response(self, intent: Intent, task_result: Dict[str, Any], stream: bool = False) -> str | Generator[str, None, None]:
        # 1. Get the specific persona for this intent
        system_prompt = self.template_engine.get_system_prompt(intent.type.value, task_result)
        
        # 2. Construct the prompt for the LLM
        # We give the LLM the user's exact words, plus a JSON-like summary of what the system did in the background.
        user_prompt = (
            f"User said: '{intent.raw_text}'\n"
            f"System action result: {task_result}\n"
            "Please provide a short, natural verbal response to the user."
        )
        
        try:
            # 3. Call the local LLM
            logger.info(f"Generating LLM response for intent: {intent.type.value}")
            
            if stream:
                return self._stream_and_format(system_prompt, user_prompt)
            else:
                raw_response = self.connector.generate(system_prompt, user_prompt, stream=False)
                # 4. Clean up the text so the TTS engine doesn't speak asterisks or emojis
                sanitized_response = TTSFormatter.format_for_speech(raw_response)
                return sanitized_response
                
        except Exception as e:
            logger.error(f"Failed to generate LLM response: {e}")
            # Fallback hardcoded response if the LLM crashes or times out
            return self._get_fallback_response(task_result)

    def _stream_and_format(self, system_prompt: str, user_prompt: str) -> Generator[str, None, None]:
        """Helper to yield chunks from the LLM, sanitizing them on the fly."""
        raw_stream = self.connector.generate(system_prompt, user_prompt, stream=True)
        
        # We accumulate a small buffer to handle things like partial markdown asterisks
        buffer = ""
        for chunk in raw_stream:
            buffer += chunk
            # If we hit a space or punctuation, we can safely format and yield the word
            if any(char in buffer for char in [' ', '.', '!', '?']):
                cleaned_chunk = TTSFormatter.format_for_speech(buffer)
                if cleaned_chunk:
                    yield cleaned_chunk + " "
                buffer = ""
                
        # Yield whatever is left
        if buffer:
            yield TTSFormatter.format_for_speech(buffer)

    def _get_fallback_response(self, task_result: Dict[str, Any]) -> str:
        """Provides a safe, non-LLM response if generation completely fails."""
        if task_result.get("status") == "success":
            return "I've completed the task, but I'm having trouble thinking of what to say next."
        else:
            return "I tried to do that, but something went wrong and my language center is offline."
