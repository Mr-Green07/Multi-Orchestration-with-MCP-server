import os
import sys
import logging
import wave
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def run_smoke_test():
    """
    A quick smoke test to verify that PiperTTS can successfully synthesize
    audio locally and that numpy audio processing works.
    """
    logger.info("Running PiperTTS Smoke Test...")
    
    # In a real setup, we would instantiate our TTSSynthesizer from src.tts.synthesizer
    try:
        from src.tts.synthesizer import TTSSynthesizer
        from src.tts.processor import TTSAudioProcessor
        
        cfg = {"tts": {"engine": "piper", "voice": "en_US-lessac-medium"}}
        tts = TTSSynthesizer(cfg)
        
        test_phrase = "Hello world. This is a smoke test to verify Piper text to speech is functioning correctly."
        logger.info(f"Synthesizing: '{test_phrase}'")
        
        raw_audio = tts.synthesize(test_phrase)
        
        if len(raw_audio) > 0:
            logger.info(f"Success! Generated {len(raw_audio)} audio samples.")
            
            # Test the post-processor
            logger.info("Testing TTSAudioProcessor...")
            processed_audio = TTSAudioProcessor.process_for_playback(raw_audio)
            logger.info("Post-processing complete.")
            
            logger.info("Smoke test passed perfectly! 🚀")
        else:
            logger.error("Failed. Synthesis returned empty audio.")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Smoke test failed with exception: {e}")
        logger.info("Note: This failure might be expected if Piper isn't fully installed or the model files are missing.")
        sys.exit(1)

if __name__ == "__main__":
    run_smoke_test()
