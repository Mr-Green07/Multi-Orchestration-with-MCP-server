import re
import logging

logger = logging.getLogger(__name__)

class TTSFormatter:
    """
    Cleans up LLM text output so that it sounds natural when spoken by a TTS engine.
    LLMs often output markdown (**, *, #), emojis, or weird spacing which sounds 
    terrible when spoken out loud.
    """
    
    @staticmethod
    def format_for_speech(text: str) -> str:
        """
        Takes raw LLM text and sanitizes it for Text-to-Speech.
        """
        if not text:
            return ""
            
        # 1. Strip all markdown bold/italic asterisks
        cleaned = re.sub(r'\*+', '', text)
        
        # 2. Strip markdown headers (#)
        cleaned = re.sub(r'#+', '', cleaned)
        
        # 3. Strip URLs (TTS engines usually read out "h t t p s colon slash slash...")
        cleaned = re.sub(r'http[s]?://\S+', 'a link', cleaned)
        
        # 4. Remove emojis (some TTS engines crash on emojis, others say the emoji name)
        # A simple regex to catch common emoji ranges
        emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)
        cleaned = emoji_pattern.sub(r'', cleaned)
        
        # 5. Clean up weird spacing or newlines
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # 6. Truncate if it's absurdly long (we don't want the assistant talking for 5 minutes)
        # We split by sentences to avoid cutting off mid-word.
        MAX_CHARS = 500
        if len(cleaned) > MAX_CHARS:
            logger.warning(f"Response truncated for TTS. Original length: {len(cleaned)}")
            # Try to find the last period within the limit
            last_period = cleaned.rfind('.', 0, MAX_CHARS)
            if last_period != -1:
                cleaned = cleaned[:last_period + 1]
            else:
                cleaned = cleaned[:MAX_CHARS] + "..."
                
        return cleaned.strip()
