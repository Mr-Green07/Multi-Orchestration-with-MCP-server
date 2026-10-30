import logging
from pathlib import Path
from typing import Dict, Any

# pyrefly: ignore [missing-import]
from src.utils.helpers import safe_read_yaml
# pyrefly: ignore [missing-import]
from src.core.constants import ROOT_DIR

logger = logging.getLogger(__name__)

class TemplateEngine:
    """
    Loads and manages the Jinja2-style system prompts defined in templates.yaml.
    
    Instead of using one massive system prompt for everything, this engine 
    injects a specific persona based on the detected intent. For example, if the 
    intent is 'PLAY_MUSIC', it loads the music persona template.
    """
    
    def __init__(self, templates_path: str | Path | None = None):
        if templates_path is None:
            templates_path = ROOT_DIR / "src" / "response_generation" / "models" / "templates.yaml"
            
        # Load all templates into memory
        self.templates = safe_read_yaml(templates_path)
        logger.debug(f"TemplateEngine loaded {len(self.templates)} prompt templates.")

    # pyrefly: ignore [bad-function-definition]
    def get_system_prompt(self, intent_name: str, context: Dict[str, Any] = None) -> str:
        """
        Retrieves the exact system prompt for a given intent.
        
        :param intent_name: The string value of the IntentType (e.g., 'greeting', 'get_weather')
        :param context: The result dictionary from the TaskExecutor. Used to format the prompt.
        :return: A fully formatted system prompt string.
        """
        if context is None:
            context = {}
            
        # Try to find a specific template for this intent, otherwise use the fallback
        raw_template = self.templates.get(intent_name)
        
        if not raw_template:
            logger.debug(f"No specific template for '{intent_name}'. Using fallback.")
            raw_template = self.templates.get("fallback", "You are a helpful AI assistant.")
            
        # If we start using actual {variables} inside templates.yaml, 
        # this is where we would format them using the context dict.
        try:
            # We use safe formatting in case the template has {braces} but no matching context key
            # For now, since they are static strings in templates.yaml, we can just return it.
            # formatted_prompt = raw_template.format(**context)
            formatted_prompt = raw_template
            return formatted_prompt.strip()
        except KeyError as e:
            logger.error(f"Missing template variable {e} for intent '{intent_name}'")
            return raw_template.strip()
