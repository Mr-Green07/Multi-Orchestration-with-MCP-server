# Quick Start Guide: Running the Offline Agent

This guide walks you through setting up and running the **Offline Llama 3.2 1B Agent** from scratch. Once the one-time downloads and dependency installations are completed, the agent operates 100% offline with zero network connectivity.

---

## 1. Prerequisites & System Requirements

- **Operating System:** Windows, Linux, or macOS.
- **Python:** Python 3.10 or 3.11 recommended.
- **Hardware:**
  - **GPU (Recommended):** NVIDIA GPU with CUDA support (uses ~1–2 GB VRAM with 4-bit NF4 quantization).
  - **CPU (Fallback):** Can run on CPU using `--no-quant` (requires more system RAM and is slower).

---

## 2. Virtual Environment & Dependency Installation

### Step 2.1: Create and Activate Virtual Environment

Open your terminal in the project root directory (`offline_agent`):

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```
*(If script execution is restricted in PowerShell, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or use Command Prompt: `.venv\Scripts\activate.bat`)*

**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

---
something changes here
### Step 2.2: Install PyTorch (CUDA build recommended)

Install the appropriate PyTorch build matching your system's CUDA driver:

**For CUDA 12.1 (example):**
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

**For CPU-only:**
```bash
pip install torch
```

---

### Step 2.3: Install Remaining Dependencies

```bash
pip install -r requirements.txt
```

> **Note on Windows & bitsandbytes:**
> `.bitsandbytes>=0.43.0` includes native Windows wheels. If you do not have an NVIDIA GPU or encounter CUDA setup issues, you can run the agent in CPU mode by appending `--no-quant`

---

## 3. Download Model Assets (One-Time Setup)

The agent needs the base model weights, and optionally the embedding model and fine-tuned QLoRA adapter.

### Step 3.1: Download Base Model (`Llama-3.2-1B-Instruct`)
The base model is gated on Hugging Face. Request access on Hugging Face, then download using the Hugging Face CLI:

```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli login
```

Download the model to `models/llama-3.2-1b-instruct`:
```bash
huggingface-cli download meta-llama/Llama-3.2-1B-Instruct --local-dir models/llama-3.2-1b-instruct
```

### Step 3.2: Download Embedding Model (For Document Search / RAG)
```bash
huggingface-cli download sentence-transformers/all-MiniLM-L6-v2 --local-dir models/all-MiniLM-L6-v2
```

### Step 3.3: Set Up QLoRA Adapter (Optional)
Place your trained adapter files into `adapters/llama-3.2-1b-qlora/`:
- `adapter_config.json`
- `adapter_model.safetensors`

*(If no adapter is provided, the agent will gracefully run using the base model and display a warning.)*

---

## 4. Smoke Test (Verify Installation)

Run the zero-dependency self-test to verify the sandbox, controller, calculator, and tools without loading heavy models or GPUs:

```bash
python selftest.py
```

To run the complete automated test suite (requires `pytest`):
```bash
pytest
```

---

## 5. (Optional) Build Document Index for RAG

If you want the agent to search through documents:

1. Place your `.pdf`, `.txt`, `.md`, or `.docx` files in the `documents/` directory.
2. Build the FAISS vector index:

```bash
python build_index.py --embed-model models/all-MiniLM-L6-v2
```

This creates a searchable vector store under `indexes/default/` containing `index.faiss`, `meta.json`, and `config.json`.

---

## 6. Running the Agent

### Option A: Standard Interactive Chat (GPU, 4-bit Quantization)
```bash
python offline_agent.py
```

### Option B: Interactive Chat with Tool Execution Logs
Displays the exact JSON tool calls and sandbox outputs:
```bash
python offline_agent.py --show-tools
```

### Option C: CPU Mode / Debugging (No GPU or CUDA)
If you don't have an NVIDIA GPU or want CPU execution:
```bash
python offline_agent.py --no-quant --debug
```

### Option D: Full Setup with RAG Index and Local SQLite Database
```bash
python offline_agent.py \
    --index indexes/default \
    --embed-model models/all-MiniLM-L6-v2 \
    --db app.db \
    --show-tools
```
*(Place any SQLite database file under `database/`, e.g., `database/app.db`)*

---

## 7. Interactive In-Session Commands

While interacting with the agent in the CLI prompt, you can use the following commands:

| Command | Description |
| :--- | :--- |
| `/help` | Display in-session help and available commands |
| `/tools` | List all 6 sandboxed tools available to the agent |
| `/show` | Toggle live display of tool calls and results |
| `/debug` | Toggle verbose debug logs to the terminal |
| `/clear` | Clear the ongoing conversation history |
| `/db <name>` | Select an active SQLite database inside `database/` |
| `/index <dir>` | Load or switch document vector index (e.g., `indexes/default`) |
| `/exit` or `/quit` | Exit the CLI session |

---

## 8. Command-Line Arguments Reference

| Argument | Default | Description |
| :--- | :--- | :--- |
| `--model-dir` | `models/llama-3.2-1b-instruct` | Directory containing base Llama model |
| `--adapter-dir` | `adapters/llama-3.2-1b-qlora` | Directory containing QLoRA adapter weights |
| `--embed-model` | `None` | Path to local sentence-transformers model |
| `--index` | `None` | Path to FAISS index directory to load on startup |
| `--db` | `None` | SQLite DB file inside `database/` to connect |
| `--no-quant` | `False` | Run in 16-bit/CPU mode without 4-bit bitsandbytes |
| `--show-tools` | `False` | Print tool calls and JSON responses in console |
| `--debug` | `False` | Enable detailed console logging |
| `--max-steps` | `4` | Maximum agent tool-calling iterations per turn |
| `--max-new-tokens` | `256` | Maximum generated tokens per model call |

---

## 9. Common Troubleshooting

- **`CUDA Setup failed` or `bitsandbytes` error:**
  - Ensure you have compatible CUDA drivers installed.
  - If on Windows without CUDA, or on CPU-only machines, use `--no-quant`.
- **Model weights not found:**
  - Verify `models/llama-3.2-1b-instruct/` contains `config.json`, `model.safetensors` (or chunked `.safetensors`), and `tokenizer.json`.
- **Out of Memory (VRAM):**
  - Use 4-bit quantization (default).
  - Reduce `--max-new-tokens 128`.
  - Type `/clear` inside the chat to prune conversation context.
- **Audit Logs:**
  - All agent interactions, model outputs, and tool activities are recorded in `logs/agent.log`.
