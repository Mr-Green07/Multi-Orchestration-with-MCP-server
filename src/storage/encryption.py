import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

class FieldEncryptor:
    """
    Handles encryption and decryption of sensitive fields at rest.
    In a Voice Assistant, this is critical for storing things like:
    - Spotify API Keys
    - Home Assistant Long-Lived Access Tokens
    - OpenAI / Anthropic API Keys (if falling back to cloud LLMs)
    """
    
    def __init__(self, key: bytes | None = None):
        """
        Initializes the encryptor. 
        In production, the key should be loaded from a secure environment variable (.env).
        If no key is provided, it attempts to load 'ENCRYPTION_KEY' from the environment,
        or generates a temporary one (warning: data encrypted with a temp key is lost on restart).
        """
        if not key:
            env_key = os.getenv("ENCRYPTION_KEY")
            if env_key:
                self.key = env_key.encode()
            else:
                logger.warning("No ENCRYPTION_KEY found in environment! Generating a temporary key for this session.")
                self.key = Fernet.generate_key()
        else:
            self.key = key
            
        self.fernet = Fernet(self.key)

    def encrypt(self, plain_text: str) -> str:
        """
        Encrypts a plaintext string into a secure, URL-safe base64-encoded string.
        """
        if not plain_text:
            return ""
        return self.fernet.encrypt(plain_text.encode('utf-8')).decode('utf-8')

    def decrypt(self, encrypted_text: str) -> str:
        """
        Decrypts an encrypted string back to plaintext.
        """
        if not encrypted_text:
            return ""
        try:
            return self.fernet.decrypt(encrypted_text.encode('utf-8')).decode('utf-8')
        except InvalidToken:
            logger.error("Failed to decrypt string: Invalid token or wrong encryption key!")
            # Rather than crashing the app, return a safe string or raise a specific error
            return "<DECRYPTION_FAILED>"
