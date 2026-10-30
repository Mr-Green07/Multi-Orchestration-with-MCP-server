import os
import yaml
from faster_whisper import WhisperModel

class WhisperASR:
    def __init__(self, config_path: str = "config/base.yaml"):
        """Initializes the offline Whisper engine utilizing parameters from base.yaml."""
        # 1. Load system configurations safely
        with open(config_path, "r") as file:
            config = yaml.safe_load(file)
            
        asr_config = config.get("asr", {})
        self.model_size = asr_config.get("model_size", "small")
        self.device = asr_config.get("device", "cpu")
        self.download_root = asr_config.get("download_root", "./offline_models")
        
        print(f"🤖 Initializing Whisper Model [{self.model_size}] on [{self.device}]...")
        
        # 2. Spin up the underlying machine learning model runner
        # compute_type="float16" provides optimal GPU speed; falls back to default on CPU
        compute_type = "float16" if self.device == "cuda" else "int8"
        
        self.model = WhisperModel(
            model_size_or_path=self.model_size,
            device=self.device,
            compute_type=compute_type,
            download_root=self.download_root
        )
        print("✅ Whisper ASR Engine successfully loaded into memory.")

    def transcribe(self, audio_file_path: str) -> str:
        """Reads a local audio file path and returns the clean text string."""
        if not os.path.exists(audio_file_path):
            raise FileNotFoundError(f"⚠️ Audio path targets an invalid location: {audio_file_path}")
            
        # beam_size=5 balances speech accuracy and resource decoding latency perfectly
        segments, info = self.model.transcribe(audio_file_path, beam_size=5)
        
        # Concatenate transcribed segments together into a single continuous phrase string
        transcription_pieces = [segment.text for segment in segments]
        full_transcript = " ".join(transcription_pieces).strip()
        
        return full_transcript