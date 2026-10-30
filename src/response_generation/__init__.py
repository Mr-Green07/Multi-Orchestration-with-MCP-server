# pyrefly: ignore [missing-import]
import yaml
from pathlib import Path

TEMPLATE_FILE = Path(__file__).parent / "models" / "templates.yaml"

with TEMPLATE_FILE.open(encoding="utf-8") as f:
    PROMPT_TEMPLATES = yaml.safe_load(f)

def get_prompt(intent: str) -> str:
    """Return the system‑prompt for the given intent."""
    return PROMPT_TEMPLATES.get(intent, PROMPT_TEMPLATES["fallback"])



PROMPT_FILE = Path(__file__).parent / "models" / "prompts.yaml"

with PROMPT_FILE.open(encoding="utf-8") as f:
    PROMPT_SAMPLES = yaml.safe_load(f)