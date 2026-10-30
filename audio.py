import logging
import sys

# Example placeholder for RealtimeSTT (a wrapper around faster-whisper/webrtcvad)
try:
    from RealtimeSTT import AudioToTextRecorder
except ImportError:
    AudioToTextRecorder = None

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def main():
    """
    Standalone demo script to test RealtimeSTT and microphone input without
    booting up the entire LLM/TTS pipeline.
    """
    if AudioToTextRecorder is None:
        logger.error("RealtimeSTT is not installed. Please run: pip install RealtimeSTT")
        sys.exit(1)
        
    logger.info("Initializing RealtimeSTT Demo...")
    logger.info("Please wait while the model loads into memory.")
    
    recorder = AudioToTextRecorder(
        model="base",
        language="en",
        spinner=True,
        compute_type="float16" # or int8 for CPU
    )
    
    logger.info("\n🎙️ Model loaded! Start speaking now. Press Ctrl+C to stop.")
    
    try:
        while True:
            # recorder.text() blocks until the user stops speaking (VAD silence), 
            # then returns the transcribed text.
            text = recorder.text()
            if text:
                logger.info(f"Transcription: {text}")
                
    except KeyboardInterrupt:
        logger.info("\nExiting RealtimeSTT Demo.")
        recorder.stop()
        sys.exit(0)

if __name__ == "__main__":
    main()
