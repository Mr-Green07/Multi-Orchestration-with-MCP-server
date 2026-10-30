
from dotenv import load_dotenv
import os

load_dotenv()


# src/core/config.py
import os
from pathlib import Path
from typing import Dict, Any
import json
from dotenv import load_dotenv


class AppConfig:
  
    
    def __init__(self) -> None:
        load_dotenv()
        
        # paths
        self.base_dir = Path(__file__).parent.parent.parent
        self.offline_models_dir = self.base_dir / "offline_models"
        
        # audio
        self.wake_threshold = float(os.getenv("WAKE_THRESHOLD", "0.8"))
        self.wake_tail_ms = int(os.getenv("WAKE_TAIL_MS", "300"))
        
        # models
        self.llm_model_name = os.getenv("LLM_MODEL_NAME", "openai/gpt-oss-120m")
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        self.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "150"))
        
        # debug / experimental
        self.debug_tts = os.getenv("DEBUG_TTS", "false").lower() in ("1", "t", "true")
        
    def load_llm_config(self) -> Dict[str, Any]:
        """Load JSON config used by the offline LLM engine."""
        cfg_path = self.offline_models_dir / "llm_config.json"
        if not cfg_path.exists():
            return {}
        
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)


config = AppConfig()

# expose commonly-used values at module level for convenience
# (optional – you can keep accessing config.llm_model_name etc)
WAKE_THRESHOLD = config.wake_threshold
WAKE_TAIL_MS = config.wake_tail_ms
LLM_MODEL_NAME = config.llm_model_name
LLM_TEMP = config.llm_temperature
LLM_MAX_TOKENS = config.llm_max_tokens
DEBUG_TTS = config.debug_tts
DATABASE_URL = os.getenv("DATABASE_URL")