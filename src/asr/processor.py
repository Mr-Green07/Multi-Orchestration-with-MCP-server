import numpy as np
import logging
import threading
from queue import Queue
import time
import librosa

logger = logging.getLogger(__name__)

def normalize_audio(audio_data: np.ndarray) -> np.ndarray:
    """
    Normalizes audio data to float32 in the range [-1.0, 1.0].
    Required for Whisper ASR input.
    """
    if not isinstance(audio_data, np.ndarray):
        audio_data = np.array(audio_data, dtype=np.float32)
        
    if audio_data.dtype == np.int16:
        # Convert int16 PCM to float32 [-1, 1]
        audio_data = audio_data.astype(np.float32) / 32768.0
    elif audio_data.dtype != np.float32:
        audio_data = audio_data.astype(np.float32)
        
    # Prevent clipping / out of bounds
    max_val = np.max(np.abs(audio_data))
    if max_val > 1.0:
        audio_data = audio_data / max_val
        
    return audio_data

def resample_audio(audio_data: np.ndarray, orig_sr: int, target_sr: int = 16000) -> np.ndarray:
    """
    Resamples audio to the target sample rate (default 16 kHz for Whisper).
    Uses librosa for high-quality resampling.
    """
    if orig_sr == target_sr:
        return audio_data
    
    logger.debug(f"Resampling audio from {orig_sr} Hz to {target_sr} Hz.")
    return librosa.resample(y=audio_data, orig_sr=orig_sr, target_sr=target_sr)

def to_mono(audio_data: np.ndarray) -> np.ndarray:
    """
    Converts stereo or multi-channel audio to mono.
    Expects shape (channels, samples) or (samples, channels).
    """
    if audio_data.ndim > 1:
        # If shape is (samples, channels), transpose to (channels, samples) for librosa
        if audio_data.shape[1] < audio_data.shape[0]:
            audio_data = audio_data.T
        return librosa.to_mono(audio_data)
    return audio_data

class ASRProcessor:
    """
    Thread-safe processor that receives audio chunks, normalizes, resamples,
    and prepares them for streaming ASR transcription.
    """
    def __init__(self, input_sample_rate=16000, target_sample_rate=16000, timeout=5):
        self.input_sample_rate = input_sample_rate
        self.target_sample_rate = target_sample_rate
        self.timeout = timeout
        
        self.audio_queue = Queue()
        self.is_processing = False
        self.processed_chunks = []
        
        logger.info(f"ASRProcessor initialized (Input SR: {input_sample_rate}, Target SR: {target_sample_rate})")

    def add_audio_chunk(self, audio_data: np.ndarray) -> bool:
        """Enqueues raw audio for processing."""
        if audio_data is None or len(audio_data) == 0:
            logger.warning("Empty audio chunk received")
            return False
            
        try:
            self.audio_queue.put(audio_data, timeout=self.timeout)
            return True
        except Exception as e:
            logger.error(f"Error adding audio chunk: {e}")
            return False

    def process_audio(self):
        """Worker loop that pulls chunks from the queue and processes them."""
        self.is_processing = True
        logger.info("ASR audio pre-processing loop started")
        
        while self.is_processing:
            try:
                raw_chunk = self.audio_queue.get(timeout=0.5)
                processed = self._process_chunk(raw_chunk)
                self.processed_chunks.append(processed)
                self.audio_queue.task_done()
            except Exception:
                # Queue empty timeout, just loop again until stopped
                continue
                
        logger.info("ASR audio pre-processing loop stopped")

    def _process_chunk(self, audio_data: np.ndarray) -> np.ndarray:
        """Applies mono conversion, resampling, and normalization."""
        # 1. Convert to mono
        audio_data = to_mono(audio_data)
        
        # 2. Normalize to float32 [-1, 1]
        audio_data = normalize_audio(audio_data)
        
        # 3. Resample to 16 kHz (if needed)
        audio_data = resample_audio(
            audio_data, 
            orig_sr=self.input_sample_rate, 
            target_sr=self.target_sample_rate
        )
        
        return audio_data

    def get_processed_audio(self) -> np.ndarray:
        """Concatenates and returns all processed chunks as a single array."""
        if not self.processed_chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self.processed_chunks)

    def clear(self):
        """Clears stored chunks and empties the queue."""
        self.processed_chunks.clear()
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except Exception:
                break
        logger.info("ASRProcessor cleared")

    def stop_processing(self):
        """Signals the worker loop to stop."""
        self.is_processing = False
        logger.info("Stop processing signal sent")

