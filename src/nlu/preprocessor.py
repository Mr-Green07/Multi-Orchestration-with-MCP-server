import re
import string
import logging
from typing import Dict, Any

# pyrefly: ignore [missing-import]
from src.nlu.exceptions import PreprocessingError
# pyrefly: ignore [missing-import]
from src.utils.helpers import safe_read_json
# pyrefly: ignore [missing-import]
from src.core.constants import ROOT_DIR

logger = logging.getLogger(__name__)

class TextPreprocessor:
    """
    Cleans and normalizes raw ASR transcripts before intent classification.
    Applies rules configured in nlu_config.json (lowercase, punctuation removal, 
    and filler word stripping).
    """
    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = ROOT_DIR / "src" / "nlu" / "models" / "nlu_config.json"
            
        # Safely load the configuration, defaulting to sensible values if missing
        self.config = safe_read_json(config_path)
        self.prep_config = self.config.get("preprocessing", {})
        
        self.do_lowercase = self.prep_config.get("lowercase", True)
        self.do_strip_punctuation = self.prep_config.get("strip_punctuation", True)
        self.do_remove_fillers = self.prep_config.get("remove_filler_words", True)
        
        # Sort filler words by length descending so longer phrases (e.g. "you know")
        # are removed before shorter parts of them (e.g. "you") if they exist.
        filler_words = self.prep_config.get("filler_words", [])
        self.filler_words = sorted(filler_words, key=len, reverse=True)
        
        # Build a regex pattern for whole-word matching of filler words
        if self.filler_words:
            # Escape regex chars just in case, though they shouldn't have any
            # pyrefly: ignore [bad-specialization]
            escaped_fillers = [re.escape(fw) for fw in self.filler_words]
            # pyrefly: ignore [no-matching-overload]
            pattern = r'\b(?:' + '|'.join(escaped_fillers) + r')\b'
            self.filler_regex = re.compile(pattern, flags=re.IGNORECASE)
        else:
            # pyrefly: ignore [bad-assignment]
            self.filler_regex = None

    def normalize(self, text: str) -> str:
        """
        Runs the full normalization pipeline on a given text string.
        
        :param text: Raw transcript from the STT engine.
        :return: Cleaned text ready for classification.
        :raises PreprocessingError: If the input is completely invalid.
        """
        if text is None or not isinstance(text, str):
            raise PreprocessingError(f"Expected a string for preprocessing, got {type(text).__name__}.")
            
        try:
            cleaned = text

            if self.do_lowercase:
                cleaned = cleaned.lower()

            if self.do_strip_punctuation:
                # Remove standard punctuation using a translation table
                translator = str.maketrans('', '', string.punctuation)
                cleaned = cleaned.translate(translator)

            if self.do_remove_fillers and self.filler_regex:
                # Remove filler words
                cleaned = self.filler_regex.sub('', cleaned)

            # Clean up any weird extra spaces left behind by removals
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to preprocess text '{text}': {e}")
            raise PreprocessingError(f"Error during text normalization: {e}")

    def process(self, text: str) -> str:
        """Alias for normalize() to support callers expecting .process()."""
        return self.normalize(text)

    def preprocess(self, text: str) -> str:
        """Alias for normalize() to support callers expecting .preprocess()."""
        return self.normalize(text)
