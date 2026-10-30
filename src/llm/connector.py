import os
import sys
import logging
import json
from typing import Dict, Any, Generator

# pyrefly: ignore [missing-import]
import requests

# Ensure project root is in sys.path when script is executed directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# pyrefly: ignore [missing-import]
from src.response_generation.exceptions import LLMTimeoutError, ResponseGenerationError

logger = logging.getLogger(__name__)

class LLMConnector:
    """
    The raw HTTP transport layer for connecting to local LLMs like Ollama or llama.cpp.xsdw
    It abstracts away the network requests, timeouts, and JSON parsing.
    """
    
    def __init__(self, base_url: str = "http://localhost:11434", model_name: str = "gemma4:e2b-it-qat", timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        
        # Determine the endpoint based on standard Ollama API
        self.generate_endpoint = f"{self.base_url}/api/generate"
        logger.info(f"LLMConnector initialized. Model: {self.model_name}, URL: {self.base_url}")

    def generate(self, system_prompt: str, user_prompt: str, stream: bool = False) -> str | Generator[str, None, None]:
        """
        Sends the fully formatted prompt to the local LLM.
        
        :param system_prompt: The behaviour instructions from the TemplateEngine.
        :param user_prompt: What the user actually said.
        :param stream: Whether to yield tokens as they arrive (for fast TTS) or wait for the full string.
        """
        payload = {
            "model": self.model_name,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": stream,
            "options": {
                "temperature": 0.7,
                "num_predict": 100 # Keep verbal responses short and snappy
            }
        }

        try:
            logger.debug(f"Sending request to LLM ({self.model_name})...")
            response = requests.post(self.generate_endpoint, json=payload, stream=stream, timeout=self.timeout)
            response.raise_for_status()
            
            if stream:
                return self._stream_response(response)
            else:
                data = response.json()
                return data.get("response", "").strip()
                
        except requests.exceptions.Timeout:
            logger.error(f"LLM request timed out after {self.timeout} seconds.")
            raise LLMTimeoutError("The local LLM took too long to respond.")
        except requests.exceptions.ConnectionError:
            logger.error(f"Could not connect to LLM server at {self.base_url}. Is Ollama running?")
            raise ResponseGenerationError("Failed to connect to the local LLM server.")
        except Exception as e:
            logger.error(f"Unexpected error communicating with LLM: {e}")
            raise ResponseGenerationError(f"LLM generation failed: {e}")

    def _stream_response(self, response: requests.Response) -> Generator[str, None, None]:
        """Helper to yield tokens dynamically if streaming is enabled."""
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    if "response" in data:
                        yield data["response"]
                except json.JSONDecodeError:
                    continue
