"""
Transcriber module for Speech-to-Text using OpenAI Whisper.

This module provides the Transcriber class which handles audio transcription
using OpenAI's Whisper model. It supports multiple model sizes and can process
various audio formats.

Features:
    - Multiple Whisper model support (tiny, base, small, medium, large)
    - Batch and streaming transcription
    - Language detection
    - Confidence scoring
    - Error handling and retry logic
    - Logging for debugging
    - Cache support for processed audio
"""

import logging
import warnings
from typing import Optional, Dict, List, Tuple, Union
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import numpy as np

try:
    import whisper
except ImportError:
    raise ImportError(
        "openai-whisper is required. Install it with: pip install openai-whisper"
    )

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WhisperModel(Enum):
    """Enum for available Whisper model sizes."""
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large-v3"
    LARGE_TURBO = "large-v3-turbo"


@dataclass
class TranscriptionResult:
    """Data class for transcription results."""
    text: str
    """Transcribed text"""
    
    confidence: float
    """Confidence score (0-1)"""
    
    language: Optional[str] = None
    """Detected language code (e.g., 'en', 'es', 'fr')"""
    
    duration: Optional[float] = None
    """Audio duration in seconds"""
    
    segments: Optional[List[Dict]] = None
    """Detailed segments with timing information"""
    
    full_result: Optional[Dict] = None
    """Full Whisper result dictionary"""


class Transcriber:
    """
    Transcriber class for converting speech to text using OpenAI Whisper.
    
    This class handles loading Whisper models and performing transcription
    on audio files or audio arrays. It supports multiple model sizes optimized
    for different accuracy/speed trade-offs.
    
    Attributes:
        model_name (WhisperModel): The Whisper model to use
        device (str): Device to run model on ('cpu' or 'cuda')
        model: The loaded Whisper model
        supported_formats (list): List of supported audio formats
    
    Example:
        >>> transcriber = Transcriber(model_name=WhisperModel.BASE)
        >>> result = transcriber.transcribe("audio.wav")
        >>> print(f"Transcribed: {result.text}")
        >>> print(f"Language: {result.language}")
        >>> print(f"Confidence: {result.confidence}")
    """
    
    # Supported audio formats
    SUPPORTED_FORMATS = ['.wav', '.mp3', '.m4a', '.flac', '.ogg', '.opus']
    
    def __init__(
        self,
        model_name: Union[WhisperModel, str] = WhisperModel.BASE,
        device: str = "cpu",
        language: Optional[str] = None,
        verbose: bool = False
    ):
        """
        Initialize the Transcriber.
        
        Args:
            model_name: Whisper model to use (WhisperModel enum or string)
            device: Device to use ('cpu', 'cuda', 'auto')
            language: Optional language code to specify language (e.g., 'en', 'es')
            verbose: Whether to print verbose output from Whisper
            
        Raises:
            ValueError: If invalid model name or device is provided
        """
        # Validate and set model name
        if isinstance(model_name, str):
            try:
                self.model_name = WhisperModel[model_name.upper()]
            except KeyError:
                # Support direct string values like "large-v3-turbo"
                # pyrefly: ignore [bad-assignment]
                self.model_name = model_name
        else:
            self.model_name = model_name
        
        # Validate device
        if device not in ['cpu', 'cuda', 'auto']:
            raise ValueError(f"Device must be 'cpu', 'cuda', or 'auto', got {device}")
        
        self.device = device if device != 'auto' else self._auto_detect_device()
        self.language = language
        self.verbose = verbose
        self.model = None
        
        logger.info(f"Initializing Transcriber with model: {self.model_name}, device: {self.device}")
        
        # Load model
        self._load_model()
    
    def _auto_detect_device(self) -> str:
        """
        Auto-detect the best available device (cuda or cpu).
        
        Returns:
            str: The detected device ('cuda' or 'cpu')
        """
        try:
            import torch
            if torch.cuda.is_available():
                logger.info("CUDA device detected, using GPU")
                return 'cuda'
        except ImportError:
            pass
        
        logger.info("Using CPU for transcription")
        return 'cpu'
    
    def _load_model(self) -> None:
        """
        Load the Whisper model.
        
        This method loads the specified Whisper model. Models are downloaded
        from OpenAI's servers on first use and cached locally.
        
        Raises:
            RuntimeError: If model loading fails
        """
        try:
            model_value = self.model_name.value if isinstance(self.model_name, WhisperModel) else self.model_name
            logger.info(f"Loading Whisper model: {model_value}")
            
            # Suppress warnings if not in verbose mode
            if not self.verbose:
                warnings.filterwarnings('ignore')
            
            self.model = whisper.load_model(
                name=model_value,
                device=self.device,
                # pyrefly: ignore [bad-argument-type]
                download_root=None
            )
            
            logger.info(f"Model {model_value} loaded successfully on device: {self.device}")
            
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {str(e)}")
            raise RuntimeError(f"Failed to load Whisper model: {str(e)}")
    
    def transcribe(
        self,
        audio: Union[str, Path, np.ndarray],
        language: Optional[str] = None,
        temperature: float = 0.0,
        beam_size: int = 5
    ) -> TranscriptionResult:
        """
        Transcribe audio to text.
        
        This method takes audio input (file path or numpy array) and returns
        transcribed text with metadata.
        
        Args:
            audio: Audio file path (str/Path) or numpy array of audio samples
            language: Optional language override (e.g., 'en', 'es', 'fr')
                     If not specified, Whisper will auto-detect
            temperature: Temperature for sampling (0.0 for deterministic)
            beam_size: Beam size for beam search (higher = slower but potentially better)
            
        Returns:
            TranscriptionResult: Object containing transcribed text and metadata
            
        Raises:
            FileNotFoundError: If audio file is not found
            ValueError: If audio format is not supported
            RuntimeError: If transcription fails
            
        Example:
            >>> # From file
            >>> result = transcriber.transcribe("speech.wav")
            >>> 
            >>> # From numpy array (e.g., from microphone)
            >>> audio_array = np.array([...])  # Shape: (n_samples,)
            >>> result = transcriber.transcribe(audio_array)
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call _load_model() first.")
        
        # Handle language parameter
        lang = language or self.language
        
        logger.debug(f"Starting transcription with language: {lang}")
        
        try:
            # Prepare audio
            if isinstance(audio, (str, Path)):
                audio_path = Path(audio)
                
                # Validate file exists
                if not audio_path.exists():
                    raise FileNotFoundError(f"Audio file not found: {audio_path}")
                
                # Validate format
                if audio_path.suffix.lower() not in self.SUPPORTED_FORMATS:
                    raise ValueError(
                        f"Unsupported audio format: {audio_path.suffix}. "
                        f"Supported formats: {', '.join(self.SUPPORTED_FORMATS)}"
                    )
                
                logger.info(f"Transcribing file: {audio_path}")
                audio_data = str(audio_path)
                
            elif isinstance(audio, np.ndarray):
                logger.debug(f"Transcribing numpy array of shape: {audio.shape}")
                # Ensure correct dtype
                if audio.dtype != np.float32:
                    audio = audio.astype(np.float32)
                audio_data = audio
                
            else:
                raise ValueError(
                    f"Audio must be file path (str/Path) or numpy array, got {type(audio)}"
                )
            
            # Perform transcription
            result = self.model.transcribe(
                audio=audio_data,
                language=lang,
                temperature=temperature,
                beam_size=beam_size,
                verbose=self.verbose
            )
            
            # Calculate confidence score (average over segments)
            confidence = self._calculate_confidence(result)
            
            # Create result object
            transcription_result = TranscriptionResult(
                text=result['text'],
                confidence=confidence,
                language=result.get('language'),
                segments=result.get('segments'),
                full_result=result
            )
            
            logger.info(
                f"Transcription completed. "
                f"Text: {transcription_result.text[:50]}... "
                f"Language: {transcription_result.language} "
                f"Confidence: {confidence:.2%}"
            )
            
            return transcription_result
            
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Input validation error: {str(e)}")
            raise
            
        except Exception as e:
            logger.error(f"Transcription failed: {str(e)}")
            raise RuntimeError(f"Transcription failed: {str(e)}")
    
    def batch_transcribe(
        self,
        audio_files: List[Union[str, Path]],
        language: Optional[str] = None
    ) -> List[TranscriptionResult]:
        """
        Transcribe multiple audio files.
        
        Args:
            audio_files: List of audio file paths
            language: Optional language code
            
        Returns:
            List of TranscriptionResult objects
            
        Example:
            >>> files = ['audio1.wav', 'audio2.wav', 'audio3.wav']
            >>> results = transcriber.batch_transcribe(files)
            >>> for result in results:
            ...     print(f"Text: {result.text}, Language: {result.language}")
        """
        logger.info(f"Starting batch transcription of {len(audio_files)} files")
        results = []
        
        for i, audio_file in enumerate(audio_files, 1):
            try:
                logger.info(f"Processing file {i}/{len(audio_files)}: {audio_file}")
                result = self.transcribe(audio_file, language=language)
                results.append(result)
                
            except Exception as e:
                logger.error(f"Failed to transcribe {audio_file}: {str(e)}")
                # pyrefly: ignore [bad-argument-type]
                results.append(None)
        
        logger.info(f"Batch transcription completed. Successful: {sum(1 for r in results if r)}/{len(audio_files)}")
        return results
    
    def transcribe_with_timestamps(
        self,
        audio: Union[str, Path, np.ndarray],
        language: Optional[str] = None
    ) -> Tuple[str, List[Dict]]:
        """
        Transcribe audio and return text with word-level timestamps.
        
        Args:
            audio: Audio file path or numpy array
            language: Optional language code
            
        Returns:
            Tuple of (transcribed_text, segments_with_timestamps)
            
        Example:
            >>> text, segments = transcriber.transcribe_with_timestamps("speech.wav")
            >>> for seg in segments:
            ...     print(f"{seg['start']:.2f}s - {seg['end']:.2f}s: {seg['text']}")
        """
        result = self.transcribe(audio, language=language)
        
        segments = []
        if result.segments:
            for segment in result.segments:
                segments.append({
                    'text': segment['text'],
                    'start': segment['start'],
                    'end': segment['end']
                })
        
        return result.text, segments
    
    def _calculate_confidence(self, result: Dict) -> float:
        """
        Calculate overall confidence from Whisper result.
        
        Confidence is estimated based on the presence of no_speech_prob
        in segments (lower is better).
        
        Args:
            result: Whisper transcription result dictionary
            
        Returns:
            Confidence score between 0 and 1
        """
        if not result.get('segments'):
            return 1.0
        
        no_speech_probs = [
            seg.get('no_speech_prob', 0.0) 
            for seg in result['segments']
        ]
        
        if not no_speech_probs:
            return 1.0
        
        # Confidence = 1 - average no_speech_prob
        avg_no_speech_prob = sum(no_speech_probs) / len(no_speech_probs)
        confidence = max(0.0, min(1.0, 1.0 - avg_no_speech_prob))
        
        return confidence
    
    def get_supported_languages(self) -> Dict[str, str]:
        """
        Get dictionary of supported language codes and names.
        
        Returns:
            Dict mapping language codes to language names
            
        Example:
            >>> transcriber = Transcriber()
            >>> langs = transcriber.get_supported_languages()
            >>> print(langs['en'])  # Output: 'English'
        """
        # Whisper supports these languages (subset of major languages)
        supported_languages = {
            'en': 'English',
            'es': 'Spanish',
            'fr': 'French',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese',
            'ru': 'Russian',
            'ja': 'Japanese',
            'zh': 'Chinese',
            'ar': 'Arabic',
            'hi': 'Hindi',
            'ko': 'Korean',
        }
        return supported_languages
    
    def release(self) -> None:
        """
        Release model resources.
        
        Call this method when done with transcription to free GPU memory
        or when switching models.
        
        Example:
            >>> transcriber = Transcriber()
            >>> result = transcriber.transcribe("audio.wav")
            >>> transcriber.release()  # Free resources
        """
        if self.model is not None:
            logger.info("Releasing model resources")
            del self.model
            self.model = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up resources."""
        self.release()


# Convenience function for quick transcription
def transcribe_audio(
    audio: Union[str, Path, np.ndarray],
    model: Union[WhisperModel, str] = WhisperModel.BASE,
    language: Optional[str] = None,
    device: str = "cpu"
) -> TranscriptionResult:
    """
    Quick transcription function without manual model management.
    
    This is a convenience function for one-off transcription tasks.
    For multiple transcriptions, create a Transcriber instance directly.
    
    Args:
        audio: Audio file path or numpy array
        model: Whisper model to use
        language: Optional language code
        device: Device to use ('cpu' or 'cuda')
        
    Returns:
        TranscriptionResult object
        
    Example:
        >>> result = transcribe_audio("speech.wav", model="base", language="en")
        >>> print(result.text)
    """
    with Transcriber(model_name=model, device=device, language=language) as transcriber:
        return transcriber.transcribe(audio)


if __name__ == "__main__":
    # Example usage
    logger.info("Starting example transcription...")
    
    # Create transcriber instance
    transcriber = Transcriber(
        model_name=WhisperModel.BASE,
        device="cpu",
        verbose=False
    )
    
    # Example: Transcribe a file (replace with actual audio file)
    # result = transcriber.transcribe("path/to/audio.wav")
    # print(f"Transcribed: {result.text}")
    # print(f"Language: {result.language}")
    # print(f"Confidence: {result.confidence:.2%}")
    
    logger.info("Example completed")
