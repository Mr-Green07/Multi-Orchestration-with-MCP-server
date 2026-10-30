import argparse
import logging
import sys

# pyrefly: ignore [missing-import]
from src.core.brain import Brain
# pyrefly: ignore [missing-import]
from src.utils.helpers import safe_read_yaml
# pyrefly: ignore [missing-import]
from src.core.constants import ROOT_DIR

# Assuming we have a Pipeline class that handles audio routing (wake -> VAD -> STT -> TTS)
# Since the diagram implies a pipeline class exists, we will mock/stub its initialization
# if it isn't fully built, but for the sake of the architecture, we wire it up here.

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Antigravity Voice Assistant Pipeline")
    parser.add_argument("--no-wake", action="store_true", help="Disable wake word detection. Instantly starts listening.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    return parser.parse_args()

def main():
    args = parse_args()
    logger.info("Starting Antigravity Voice Assistant...")
    
    # 1. Load Configuration
    config_path = ROOT_DIR / args.config
    cfg = safe_read_yaml(config_path)
    
    # 2. Initialize the Brain
    # The Brain handles STT -> NLU -> Task -> LLM -> TTS
    brain = Brain(cfg)
    
    # 3. Initialize the Audio Pipeline (Wake -> VAD)
    # The pipeline continuously listens to the microphone, detects wake words (if enabled),
    # records utterance via VAD, and then passes the audio chunk to brain.on_utterance()
    logger.info("Initializing Audio Pipeline (Wake -> VAD)...")
    try:
        # pyrefly: ignore [missing-import]
        from src.asr.pipeline import Pipeline
        pipeline = Pipeline(cfg, on_utterance=brain.on_utterance, enable_wake_word=not args.no_wake)
        
        logger.info(f"Pipeline started. Wake word detection is {'DISABLED' if args.no_wake else 'ENABLED'}.")
        pipeline.start()
        
    except ImportError:
        logger.warning("src.asr.pipeline module not found. The pipeline will not run.")
        logger.info("This is the main entry point for the always-on voice assistant.")
        
    except KeyboardInterrupt:
        logger.info("Shutting down Voice Assistant.")
        sys.exit(0)

if __name__ == "__main__":
    main()