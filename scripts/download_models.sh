#!/usr/bin/env bash
# Downloads every model the assistant needs (~2.4 GB total).
set -euo pipefail
mkdir -p models

# --- LLM: Qwen2.5-3B-Instruct Q4_K_M (~2.0 GB) ---
hf download Qwen/Qwen2.5-3B-Instruct-GGUF \
    qwen2.5-3b-instruct-q4_k_m.gguf --local-dir models

# --- TTS: Piper voice (~65 MB) ---
hf download rhasspy/piper-voices \
    en/en_US/lessac/medium/en_US-lessac-medium.onnx \
    en/en_US/lessac/medium/en_US-lessac-medium.onnx.json --local-dir models

# --- VAD: Silero VAD v5 (~2 MB) ---
curl -L -o models/silero_vad.onnx \
    https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx

# faster-whisper (STT) and openWakeWord download their own weights on first run.
# llama-server binary: grab a CUDA release from https://github.com/ggml-org/llama.cpp/releases
python3 -c "import openwakeword.utils as u; u.download_models()"  # wake-word feature + phrase models (offline after this)
echo "done."
