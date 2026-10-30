# 🎤 Offline Speech Recognition System (ASR) — Voice Assistant

An **offline-first voice assistant** built around OpenAI Whisper. It combines a
real-time voice pipeline (wake word → VAD → speech-to-text → response → TTS)
with a **FastAPI REST backend** and a **glass-design desktop app** for
transcribing audio with a click of a floating microphone.

> Everything runs locally — no audio ever leaves your machine.

---

## ✨ What's in the box

| Layer | Entry point | What it does |
|-------|-------------|--------------|
| 🖥️ **Desktop app** | `frontend/desktop.py` | Glass-design UI in a native window (pywebview) with a floating mic button |
| 🌐 **REST API** | `server.py` | FastAPI backend: `/api/v1/transcribe` + status/model endpoints, serves the UI |
| 🗣️ **Voice pipeline** | `main.py` | Always-on assistant: wake word → VAD endpointing → utterance capture → reply |
| 🧠 **Model manager** | `models.py` | Loads/caches Whisper models (tiny → large), device + language config |

---

## 🚀 Quick Start

### 1. Install

```bash
# from the project root
python -m venv venv
venv\Scripts\activate           # Windows
# source venv/bin/activate      # macOS / Linux

pip install -r requirement.txt
pip install pywebview            # optional: native desktop window
```

FFmpeg is required by Whisper — download from [ffmpeg.org](https://ffmpeg.org/download.html).

### 2. Run the desktop application  🖥️

```bash
python frontend/desktop.py
```

This starts the backend **and** opens the glass UI in a native window
(or your browser if pywebview isn't installed). Tap the floating
microphone to record, or upload/drag-drop an audio file.

### 3. Or run the API server only  🌐

```bash
python server.py
# UI:      http://localhost:8000/
# Docs:    http://localhost:8000/docs   (Swagger UI, when FastAPI is installed)
# Health:  http://localhost:8000/health
```

### 4. Or run the always-on voice pipeline  🗣️

```bash
python main.py
# say the wake word, speak, get a reply chime (brain wiring in progress)
```

---

## 🔄 API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/health` | Liveness check |
| `GET`  | `/api/v1/status` | System + model status |
| `GET`  | `/api/v1/model-info` | Whisper model details |
| `GET`  | `/api/v1/supported-formats` | Allowed audio formats |
| `GET`  | `/api/v1/languages` | Common language codes |
| `POST` | `/api/v1/transcribe` | Multipart audio upload → transcript JSON |

**Example**

```bash
curl -X POST http://localhost:8000/api/v1/transcribe -F "file=@audio.mp3"
```

```json
{
  "success": true,
  "transcript": "This is the transcribed text",
  "language": "en",
  "duration": 5.2,
  "processing_time": 2.34,
  "timestamp": "2026-07-07T12:00:00+00:00"
}
```

Supported formats: **MP3, WAV, M4A, FLAC, OGG, WebM** · 99+ languages (auto-detect or `language` form field).

---

## 📁 Project Structure (actual)

```
ASR/
├── main.py                  🗣️ Voice pipeline: capture → wake → VAD → reply loop
├── server.py                🌐 FastAPI backend + serves frontend (stdlib fallback included)
├── models.py                🧠 WhisperModelManager (load/cache/info/device)
├── audio.py                 🎙️ RealtimeSTT live-transcription demo
├── whiper_test.py           🔊 Piper TTS smoke test
├── config.yaml              ⚙️ Audio + wake-word pipeline tuning knobs
├── .env                     ⚙️ Model / API / logging configuration
├── requirement.txt          📦 Dependencies (also see requirements/)
│
├── frontend/                🖥️ Glass-design desktop app
│   ├── desktop.py           ⭐ Launch as a desktop application
│   ├── index.html           UI: floating mic, transcript panel, engine card
│   ├── styles.css           Glassmorphism theme + colour-splash background
│   └── app.js               Recording, upload, API calls
│
├── src/
│   ├── core/                FSM (state.py), event bus (events.py), config
│   ├── audio/               Mic capture, wake word, Silero VAD, playback
│   ├── asr/                 Whisper transcriber(s), processor, exceptions
│   ├── nlu/                 Intent detection (rule-based Phase 1)
│   ├── response_generation/ Ollama/LLM response engine, templates
│   ├── storage/             SQLAlchemy models + SQLite conversation log
│   ├── tts/                 Piper TTS (exceptions; synth in progress)
│   ├── wake_word/           openWakeWord live detector demo
│   ├── api/                 API schemas (routers scaffolded)
│   ├── tasks/, utils/, llm/ Scaffolding for later phases
│   └── __init__.py          Package overview docstring
│
├── tests/                   Unit tests: capture, VAD, wake word, playback
├── docs/                    📚 CODE_DOCUMENTATION.md — every file & function
├── offline_models/          Whisper .pt + Piper .onnx voices (local)
├── scripts/                 Model download helpers (Qwen GGUF, Piper, Silero)
└── data/                    Logs, SQLite DB, cache, temp uploads
```

---

## ⚙️ Configuration

All knobs live in **`.env`** (model size/device/language, API host/port,
upload limits, logging) and **`config.yaml`** (audio capture + wake-word
thresholds). Key `.env` entries:

```env
MODEL_SIZE=small        # tiny | base | small | medium | large
DEVICE=cuda             # cpu | cuda
LANGUAGE=en
API_PORT=8000
MAX_UPLOAD_SIZE=500     # MB
```

Whisper weights are cached in `offline_models/` on first load
(`medium.pt` and `small.pt` are already present).

---

## 🧪 Testing

```bash
python -m pytest tests/          # unit tests (capture, VAD, wake word, playback)
python whiper_test.py            # Piper TTS smoke test
```

---

## 📚 Documentation

- **[docs/CODE_DOCUMENTATION.md](docs/CODE_DOCUMENTATION.md)** — file-by-file
  reference: what every file is for and what every function does.
- `src/core/state.py` docstring — the assistant state machine diagram.
- `http://localhost:8000/docs` — interactive Swagger API docs (server running).

---

## 🗺️ Status / Roadmap

| Component | Status |
|-----------|--------|
| Whisper model manager (`models.py`) | ✅ Working |
| FastAPI backend (`server.py`) | ✅ Working (with stdlib fallback) |
| Glass desktop app (`frontend/`) | ✅ Working |
| Audio pipeline: capture / wake / VAD / playback | ✅ Implemented + unit tests |
| Pipeline "brain" (STT → intent → LLM → TTS wiring) | 🔧 In progress (`main.py` placeholder reply) |
| NLU / response generation / storage | 🔧 Early modules present |
| API routers under `src/api/` | 📋 Scaffolded |

---

## 🙏 Acknowledgments

**OpenAI Whisper** · **FastAPI** · **Silero VAD** · **openWakeWord** · **Piper TTS** · **RealtimeSTT**

**Version:** 1.1.0 · **Last updated:** July 7, 2026
