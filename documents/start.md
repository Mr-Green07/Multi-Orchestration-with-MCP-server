# How to Start This Project

## Prerequisites

- Python 3.10 or later
- NVIDIA GPU with CUDA support (recommended for 4-bit QLoRA inference)
- Alternatively, CPU mode with `--no-quant` flag (slower, higher memory)

## 1. Set Up the Environment

Create a virtual environment and install dependencies (do this once, online):

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

# Install a CUDA-matched PyTorch build first (see https://pytorch.org).
# Example for CUDA 12.1:
pip install torch --index-url https://download.pytorch.org/whl/cu121

# Then the rest:
pip install -r requirements.txt
```

> **Note:** `bitsandbytes` (4-bit quantization) requires an NVIDIA GPU + CUDA. On CPU-only machines, run with `--no-quant` (slower, higher memory).

## 2. Download Models and Adapter

The base Llama model is gated on Hugging Face — request access once, then:

```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli login                      # paste a token with access to the repo

# Base model -> models/llama-3.2-1b-instruct/
huggingface-cli download meta-llama/Llama-3.2-1B-Instruct \
    --local-dir models/llama-3.2-1b-instruct

# Embedding model for retrieval -> models/all-MiniLM-L6-v2/
huggingface-cli download sentence-transformers/all-MiniLM-L6-v2 \
    --local-dir models/all-MiniLM-L6-v2
```

**Your QLoRA adapter:** copy your trained adapter into `adapters/llama-3.2-1b-qlora/`. It must contain `adapter_config.json` and the adapter weights (`adapter_model.safetensors`).

> (No adapter yet? The agent still runs on the base model and prints a warning.)

## 3. Prepare Documents

Place your source documents to index in the `documents/` folder. Supported formats: PDF, TXT, MD, DOCX.

## 4. Build the Document Index

Build the FAISS index for document retrieval:

```bash
python build_index.py
```

## 5. Run the Agent

Start the interactive CLI:

```bash
python offline_agent.py
```

Or run the self-test (zero-dependency smoke test, no pytest needed):

```bash
python selftest.py
```

## 6. Troubleshooting

- **CUDA out of memory:** Try `--no-quant` flag for CPU mode, or reduce batch sizes.
- **Model not found:** Ensure the model files are in `models/llama-3.2-1b-instruct/` and the adapter is in `adapters/llama-3.2-1b-qlora/`.
- **Permission issues:** Run with appropriate permissions for the `workspace/` directory.