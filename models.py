import os
import logging
from pathlib import Path
from typing import Optional
import whisper
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WhisperModelManager:

    # Whisper model catalogue: approximate download size and parameter count.
    # Referenced by __init__ validation, load_model() and get_model_info().
    VALID_MODELS = {
        'tiny':   {'size': '39 MB',   'params': 39_000_000},
        'base':   {'size': '74 MB',   'params': 74_000_000},
        'small':  {'size': '244 MB',  'params': 244_000_000},
        'medium': {'size': '769 MB',  'params': 769_000_000},
        'large':  {'size': '1550 MB', 'params': 1_550_000_000},
    }

    def __init__(
        self,
        # pyrefly: ignore [bad-function-definition]
        model_size: str = None,
        # pyrefly: ignore [bad-function-definition]
        device: str = None,
        # pyrefly: ignore [bad-function-definition]
        language: str = None,
        # pyrefly: ignore [bad-function-definition]
        model_dir: str = None
    ):
        # Load from .env (via load_dotenv above); explicit args take priority
        self.model_size = model_size or os.getenv('MODEL_SIZE')
        self.device = device or os.getenv('DEVICE')
        self.language = language or os.getenv('LANGUAGE')
        self.model_dir = Path(model_dir or os.getenv('MODEL_DIR', './offline_models'))
        self.model = None
        
        # Validate model size
        # pyrefly: ignore [missing-attribute]
        if self.model_size not in self.VALID_MODELS:
            logger.warning(
                # pyrefly: ignore [missing-attribute]
                f"Invalid model size '{self.model_size}'. "
                f"Valid options: {list(self.VALID_MODELS.keys())}. "
                f"Using 'small' as default."
            )
            self.model_size = 'small'
        
        # Create model directory if it doesn't exist
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            f"WhisperModelManager initialized: "
            f"model={self.model_size}, device={self.device}, language={self.language}"
        )
    
    def load_model(self) -> whisper.Whisper:
        
        if self.model is not None:
            logger.info("Model already loaded, returning cached instance.")
            return self.model
        
        try:
            logger.info(f"Loading Whisper model: {self.model_size} on {self.device}...")
            
            # Load from the local model directory (offline-first);
            # weights are downloaded there on first use and reused after.
            self.model = whisper.load_model(
                # pyrefly: ignore [bad-argument-type]
                self.model_size,
                device=self.device,
                download_root=str(self.model_dir)
            )
            
            # pyrefly: ignore [missing-attribute]
            model_info = self.VALID_MODELS[self.model_size]
            logger.info(
                f"Successfully loaded {self.model_size} model "
                f"(~{model_info['size']}) on {self.device}"
            )
            
            return self.model
            
        except Exception as e:
            logger.error(f"Failed to load model: {str(e)}")
            raise RuntimeError(f"Model loading failed: {str(e)}")
    
    def unload_model(self) -> None:
    
        if self.model is not None:
            self.model = None
            logger.info("Model unloaded from memory")
    
    def get_model_info(self) -> dict:
    
        # pyrefly: ignore [missing-attribute]
        model_info = self.VALID_MODELS.get(self.model_size, {})
        
        return {
            'model_size': self.model_size,
            'approximate_size': model_info.get('size', 'Unknown'),
            'parameters': model_info.get('params', 0),
            'device': self.device,
            'language': self.language,
            'model_dir': str(self.model_dir),
            'model_loaded': self.model is not None
        }
    
    def list_downloaded_models(self) -> list:
       
        if not self.model_dir.exists():
            return []
        
        models = list(self.model_dir.glob('*.pt'))
        logger.info(f"Found {len(models)} downloaded model(s)")
        return [str(m) for m in models]
    
    def get_device_info(self) -> dict:
    
        import torch
        
        device_info = {
            'device': self.device,
            'torch_version': torch.__version__,
            'cuda_available': torch.cuda.is_available(),
        }
        
        if torch.cuda.is_available() and self.device == 'cuda':
            # pyrefly: ignore [no-matching-overload]
            device_info.update({
                'cuda_version': torch.version.cuda,
                'gpu_name': torch.cuda.get_device_name(0),
                'gpu_memory_gb': torch.cuda.get_device_properties(0).total_memory / 1e9
            })
        
        return device_info

def get_default_model() -> whisper.Whisper:
   
    manager = WhisperModelManager()
    return manager.load_model()

_model_manager: Optional[WhisperModelManager] = None

def initialize_model_manager(
    # pyrefly: ignore [bad-function-definition]
    model_size: str = None,
    # pyrefly: ignore [bad-function-definition]
    device: str = None,
    # pyrefly: ignore [bad-function-definition]
    language: str = None
) -> WhisperModelManager:
   
    global _model_manager
    _model_manager = WhisperModelManager(
        model_size=model_size,
        device=device,
        language=language
    )
    return _model_manager


def get_model_manager() -> WhisperModelManager:

    global _model_manager
    if _model_manager is None:
        _model_manager = initialize_model_manager()
    return _model_manager


if __name__ == '__main__':
    # Example usage
    logger.info("Testing WhisperModelManager...")
    
    manager = WhisperModelManager()
    logger.info(f"Model info: {manager.get_model_info()}")
    logger.info(f"Device info: {manager.get_device_info()}")
    
    # Load model
    model = manager.load_model()
    logger.info("Model loaded successfully!")
    
    # List downloaded models
    downloaded = manager.list_downloaded_models()
    logger.info(f"Downloaded models: {downloaded}")
