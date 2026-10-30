# 📚 Code Documentation — Offline ASR / Voice Assistant

A file-by-file reference for the whole project: **what each file is for, how to
use it, and what every function/class does.**

> Files marked 🔧 are early-stage; files marked 📋 are empty scaffolds reserved
> for future phases and are not documented function-by-function.

---

## Table of Contents

1. [Root files](#1-root-files)
   - [main.py](#mainpy) · [server.py](#serverpy) · [models.py](#modelspy)
   - [audio.py](#audiopy) · [whiper_test.py](#whiper_testpy)
   - [config.yaml](#configyaml) · [.env](#env) · [requirement.txt](#requirementtxt)
2. [frontend/ — glass desktop app](#2-frontend--glass-desktop-app)
3. [src/core/ — state machine & events](#3-srccore--state-machine--events)
4. [src/audio/ — microphone, wake word, VAD, playback](#4-srcaudio--microphone-wake-word-vad-playback)
5. [src/asr/ — speech-to-text](#5-srcasr--speech-to-text)
6. [src/nlu/ — intent detection](#6-srcnlu--intent-detection)
7. [src/response_generation/ — LLM replies](#7-srcresponse_generation--llm-replies)
8. [src/storage/ — database](#8-srcstorage--database)
9. [src/wake_word/ — standalone detector demo](#9-srcwake_word--standalone-detector-demo)
10. [src/api/ and other scaffolds](#10-srcapi-and-other-scaffolds)
11. [tests/](#11-tests)
12. [scripts/ and data folders](#12-scripts-and-data-folders)

---

# 1. Root files

## `main.py`

**Purpose:** entry point of the **always-on voice pipeline**. Wires microphone
capture → wake-word detection → VAD endpointing → (reply) → speaker playback
into one program with a strict thread model:

- **PortAudio input thread** — mic callback pushes audio into a bounded queue (never blocks).
- **Audio worker thread** — feeds the wake-word engine continuously, feeds the
  VAD only while LISTENING, publishes events, and performs barge-in playback
  kills inline.
- **Main loop** — consumes events and owns *all* state transitions.

**Usage:** `python main.py` → say the wake word → speak → get a confirmation
chime (the "brain" — STT → router → agent → TTS — is a pluggable callback,
currently a placeholder).

### `class Pipeline`

| Member | Purpose |
|---|---|
| `__init__(cfg, *, capture=None, wake=None, vad=None, playback=None, on_utterance=None)` | Builds the pipeline from `config.yaml`. Every component is injectable for tests; heavy ones (wake word, VAD, playback) import lazily. `on_utterance` is the "brain" plug — a callback `(audio_16k_int16, pipeline)` invoked with each finished utterance. |
| `_audio_worker()` | Runs on the audio thread. Re-buffers mic chunks to each engine's frame size; on a wake-word hit: barge-in kill if SPEAKING, `wake` event if IDLE. While LISTENING, pushes frames through the VAD and publishes its events. |
| `run_forever()` | Starts the audio worker and runs the main event loop until Ctrl-C. Polls the event bus with a 0.2 s timeout so the stop flag is honoured. |
| `shutdown()` | Sets the stop flag, stops capture, closes playback. |
| `_handle(ev)` | The **only** place state transitions happen. `wake`/`barge_in` → LISTENING (+ chime + VAD warm-start); `timeout` → back to IDLE; `endpoint` → `_respond()` with the captured utterance. |
| `_warm_start_vad()` | Feeds the pre-roll tail (audio spoken *while* the wake word was still being confirmed) into the endpointer, so "alexa set a timer" said in one breath loses nothing. |
| `_respond(utt_audio)` | THINKING → SPEAKING; raises the wake threshold during our own speech; calls `on_utterance`; waits for playback (returns early on barge-in); guarantees a sane state in `finally`. |
| `_placeholder_reply(audio, pipeline)` | Temporary brain: logs the utterance length and plays a two-tone "heard you" beep. Replace via the `on_utterance` argument. |

---

## `server.py`

**Purpose:** the **FastAPI backend server**. Exposes the transcription REST API
and serves the glass frontend at `/`. If FastAPI/uvicorn aren't installed it
automatically drops to a dependency-free stdlib implementation of the same
endpoints, so the UI always works.

**Usage:** `python server.py` → http://localhost:8000 (UI at `/`, Swagger docs
at `/docs` when FastAPI is installed). Configuration comes from `.env`
(`API_HOST`, `API_PORT`, `API_PREFIX`, `MAX_UPLOAD_SIZE`).

| Function | Purpose |
|---|---|
| `model_info()` | Returns Whisper model metadata from `models.WhisperModelManager`; if `whisper` isn't importable, returns `.env` values plus an `error` field instead of crashing. |
| `run_transcription(tmp_path, language)` | Shared core used by both server flavours: loads the model (lazily, cached), calls `model.transcribe()`, and shapes the JSON response (`transcript`, `language`, `duration`, `processing_time`, `timestamp`). Falls back to a stub message when Whisper isn't installed. |
| `build_fastapi_app()` | Builds the FastAPI app: CORS middleware, all six endpoints, and a `StaticFiles` mount of `frontend/` at `/`. Endpoint handlers validate extension (`SUPPORTED_FORMATS`), size (`MAX_UPLOAD_MB`) and emptiness before transcribing. |
| `run_fallback_server()` | stdlib `http.server` twin of the API for machines without FastAPI. `Handler._json()` writes JSON responses; `_static()` serves frontend files with path-traversal protection; `do_GET`/`do_POST` route the same paths; multipart parsing extracts the first file part. |
| `main()` | Tries `import uvicorn` → run FastAPI; on `ImportError` → `run_fallback_server()`. |

**Endpoints:** `GET /health`, `GET /api/v1/status`, `GET /api/v1/model-info`,
`GET /api/v1/supported-formats`, `GET /api/v1/languages`,
`POST /api/v1/transcribe` (multipart `file`, optional `language`).

---

## `models.py`

**Purpose:** the **Whisper model manager** — loading, caching and inspecting
OpenAI Whisper models. Configured from `.env` (`MODEL_SIZE`, `DEVICE`,
`LANGUAGE`, `MODEL_DIR`).

**Usage:** `from models import get_model_manager` then
`get_model_manager().load_model()`. Or run standalone: `python models.py`
(loads the model and prints info).

### `class WhisperModelManager`

| Member | Purpose |
|---|---|
| `VALID_MODELS` | Class-level catalogue of the five model sizes with approximate download size and parameter count; used for validation and `get_model_info()`. |
| `__init__(model_size=None, device=None, language=None, model_dir=None)` | Reads settings from arguments or `.env`; validates the model size (falls back to `small`); creates the model directory. |
| `load_model()` | Loads the Whisper model once via `whisper.load_model()` with `download_root=model_dir` (offline-first) and caches it — repeated calls return the cached instance. Raises `RuntimeError` on failure. |
| `unload_model()` | Drops the reference so memory can be reclaimed. |
| `get_model_info()` | Dict of `model_size`, `approximate_size`, `parameters`, `device`, `language`, `model_dir`, `model_loaded`. |
| `list_downloaded_models()` | Lists `*.pt` files already in the model directory. |
| `get_device_info()` | Torch/CUDA diagnostics: torch version, CUDA availability, GPU name and memory when applicable. |

### Module-level helpers

| Function | Purpose |
|---|---|
| `get_default_model()` | One-liner: construct a manager and return the loaded model. |
| `initialize_model_manager(model_size, device, language)` | Creates and stores the global singleton manager with explicit settings. |
| `get_model_manager()` | Returns the singleton, creating it with `.env` defaults on first use. This is what `server.py` uses. |

---

## `audio.py`

**Purpose:** minimal **live-transcription demo** using the RealtimeSTT library.
Independent of the rest of the project — useful for checking your mic + GPU.

**Usage:** `python audio.py` → speak → finished sentences print continuously.
Configured for `model="medium"`, `device="cuda"`, `compute_type="int8"`.

---

## `whiper_test.py`

**Purpose:** **Piper TTS smoke test**: synthesizes a sentence to `output.wav`
using the local voice `offline_models/en_US-lessac-medium.onnx`. (The
commented-out block at the top is the equivalent Whisper STT smoke test for
`sample-0.mp3`.)

**Usage:** `python whiper_test.py` → creates `output.wav`.

---

## `config.yaml`

**Purpose:** tuning knobs for the *voice pipeline* (`main.py`).

| Section | Keys |
|---|---|
| `audio` | `sample_rate` (16000), `frame_ms`, `preroll_ms` (audio kept from *before* the wake word), `device_name` (mic substring; null = OS default), `queue_max_chunks` (overflow bound). |
| `wakeword` | `model` (path/name of .onnx), `threshold`, `speaking_threshold` (raised bar during TTS for barge-in), `consecutive_frames` (debounce), `cooldown_s` (refractory period). |

## `.env`

**Purpose:** configuration for the *model manager and API server*: model
(`MODEL_SIZE`, `DEVICE`, `LANGUAGE`, `MODEL_DIR`, `PIPER_MODEL`), API
(`API_HOST`, `API_PORT`, `API_PREFIX`), uploads (`MAX_UPLOAD_SIZE`,
`ALLOWED_FORMATS`, `TEMP_UPLOAD_DIR`), output (`OUTPUT_FORMAT`, `OUTPUT_DIR`),
logging (`LOG_LEVEL`, `LOG_FILE`), database (`DATABASE_URL` — SQLite), Redis
cache flags (Phase 2), and feature flags.

## `requirement.txt`

**Purpose:** pip dependencies — Whisper + audio stack (openai-whisper, silero,
librosa, sounddevice, pyaudio), web stack (fastapi, uvicorn, python-multipart,
pydantic), config (python-dotenv, pyyaml), storage (sqlalchemy, redis), and dev
tools (pytest, black, flake8). `requirements/` holds the same split into
`base/dev/test/docs/prod`.

---

# 2. `frontend/` — glass desktop app

## `frontend/desktop.py`

**Purpose:** run the project as a **desktop application**. Starts the backend
in a background thread and opens the UI in a native window.

**Usage:** `python frontend/desktop.py`. Needs `pip install pywebview` for the
native window; without it, it opens the default browser instead (same UI).

| Function | Purpose |
|---|---|
| `_wait_for_backend(timeout=30)` | Polls `GET /health` every 0.3 s until the backend answers (model imports can be slow) so the window never opens on a dead page. |
| `main()` | Starts `server.main()` in a daemon thread → waits for health → `webview.create_window(...)` + `webview.start()` (blocks until the window closes). On `ImportError` falls back to `webbrowser.open()` and keeps the process alive for the backend. |

## `frontend/index.html`

**Purpose:** the app's single page. Structure: animated colour-splash
background (`.bg` + four gradient blobs + noise layer), a glass top bar with
connection status pill, the **Transcript panel** (glass card with upload
button, drag-and-drop zone and language chip), the **Engine card** (model /
device / language / loaded), and the **floating microphone button**
(`#mic-fab`) with two ripple rings.

## `frontend/styles.css`

**Purpose:** the glassmorphism theme. Key pieces:

- `:root` variables — glass background/border/highlight colours, radius, blur.
- `.bg`, `.blob--*`, `@keyframes drift` — the drifting colour-splash background.
- `.glass` / `.glass-soft` — frosted-glass primitives (backdrop-filter blur + saturate, inset highlights).
- `.status-pill` + `.rec/.busy/.err` states — LED colours for the top bar.
- `.mic-fab` + `@keyframes float / ripple` — the floating mic: gradient fill, hover scale, idle float animation, and expanding rings while recording.

## `frontend/app.js`

**Purpose:** all client logic. Talks to the backend at the same origin
(`API_BASE = ""`).

| Function | Purpose |
|---|---|
| `setStatus(kind, text)` | Updates the status pill (`idle`/`rec`/`busy`/`err`) and its LED colour. |
| `showTranscript(data)` | Renders the transcript text, sets the language chip and the "Xs audio · Ys processing" metadata line. |
| `showError(html)` | Replaces the transcript area with an error/help message. |
| `sendAudio(blob, filename)` | POSTs the audio as `multipart/form-data` to `/api/v1/transcribe`, then `showTranscript` or `showError`. |
| file-input `change` + panel `drop` handlers | Route uploaded or dragged-in audio files to `sendAudio`. |
| `toggleRecord()` | First tap: `getUserMedia({audio}) → MediaRecorder.start()`, mic turns red with ripples. Second tap: stops, bundles chunks into a webm blob and sends it. Graceful error if the mic is blocked. |
| `stopRecord()` | Stops the recorder and clears the recording UI state. |
| boot IIFE | On load: `GET /api/v1/model-info` to fill the Engine card and set the pill to *Ready* (or *Backend offline* with instructions). |

---

# 3. `src/core/` — state machine & events

## `src/core/state.py`

**Purpose:** the assistant's **finite-state machine**.

```
IDLE ─wake→ LISTENING ─endpoint→ THINKING ─answer→ SPEAKING ─played→ IDLE
                │timeout            ⇅ tool               │barge-in
                └──→ IDLE          ACTING                └──→ LISTENING
```

| Member | Purpose |
|---|---|
| `class State` | Enum: `IDLE` (only wake engine active), `LISTENING` (VAD collecting), `THINKING` (STT+LLM), `ACTING` (tool running), `SPEAKING` (TTS playing). |
| `class InvalidTransition` | Raised on any transition not in the legal table — wiring bugs explode loudly at the exact wrong line instead of corrupting state. |
| `StateMachine.LEGAL` | The set of allowed `(from, to)` pairs (9 transitions, including barge-in `SPEAKING→LISTENING`). |
| `StateMachine.state` | Current state (property, thread-safe). |
| `StateMachine.transition(new)` | Validates against `LEGAL` under a lock, logs the change, and fires the optional `on_change(old, new)` hook. Only the pipeline calls this. |

## `src/core/events.py`

**Purpose:** tiny **thread-safe event bus** — one queue of `Event` dataclasses.
The audio thread publishes; the main loop consumes; components never call each
other across threads.

| Member | Purpose |
|---|---|
| `class Event` | `kind` (`"wake" \| "barge_in" \| "speech_start" \| "endpoint" \| "timeout"`) + optional `payload`. |
| `EventBus.publish(event)` | Enqueue (non-blocking for producers). |
| `EventBus.next(timeout)` | Dequeue or `None` on timeout — lets the main loop poll its stop flag. |

## `src/core/config.py` 🔧

Loads `.env` and exposes `DATABASE_URL`. (Five lines; more config loading to come.)

## `src/core/pipeline.py` 🔧

An 8-line wiring sketch of the capture → rebuffer → wake/VAD flow. The real
implementation lives in `main.py`; keep this as a design note.

---

# 4. `src/audio/` — microphone, wake word, VAD, playback

## `src/audio/capture.py`

**Purpose:** microphone ownership — delivers a clean stream of **16 kHz mono
int16 chunks** regardless of device sample rate, plus the pre-roll ring that
preserves audio from *before* the wake word.

| Member | Purpose |
|---|---|
| `class Rebuffer` | Converts arbitrary-length arrays into fixed-length frames. `push(samples)` yields complete frames and keeps the remainder. One instance per consumer (wake word needs 1280-sample frames, Silero needs 512). |
| `class PrerollRing` | Rolling window of the last `ms` milliseconds. `push(chunk)` appends and trims whole chunks; `snapshot()` returns the window as one array — called once per wake to seed STT so words spoken during wake confirmation aren't lost. Thread-safe. |
| `find_input_device(name_part)` | Resolves a mic by name substring (`None` → OS default). Raises `LookupError` with a helpful hint listing how to see devices. |
| `class MicCapture` | Owns the `sounddevice.InputStream`. |
| `MicCapture._probe_rate()` | Negotiates a supported sample rate with the device (16 kHz preferred, else device default). |
| `MicCapture._make_resampler(native)` | Builds a polyphase resampler `native → 16 kHz` (identity if already 16 kHz). |
| `MicCapture._callback(indata, ...)` | PortAudio callback: convert, resample, push to the bounded queue; counts drops/overflows instead of logging (callbacks must not block). |
| `MicCapture.chunks()` | Generator the audio worker iterates: yields 16 kHz chunks, feeds the pre-roll ring, reports drop counters. |
| `MicCapture.stop()` | Stops and closes the stream. |

## `src/audio/vad.py`

**Purpose:** voice-activity detection + **endpointing** (Silero VAD v5 via
onnxruntime). Turns per-frame speech probabilities into utterance boundaries:

- *hysteresis* — enter speech at `speech_threshold` (0.5), count silence only below `exit_threshold` (0.35);
- *audio clock* — silence measured in frames (512 samples = 32 ms), never wall time;
- *pre-pad* — utterance seeded with frames just before detection so soft onsets survive;
- *auto-reset* — RNN state cleared after every endpoint/timeout.

| Member | Purpose |
|---|---|
| `_ms_to_frames(ms)` | Millisecond → frame-count conversion helper. |
| `class VadEvent` | `kind` (`"speech_start" | "endpoint" | "timeout"`), `audio` (full utterance int16 on endpoint), `reason` (`"silence"`/`"max_length"`). |
| `class SileroOnnx` | Thin ONNX wrapper. `__call__(frame_f32)` → speech probability; `reset()` clears the RNN hidden state (Silero is stateful and bleeds across utterances otherwise). |
| `class VadEndpointer` | The state machine (`WAITING ↔ IN_SPEECH`). |
| `VadEndpointer.__init__(cfg, model=None)` | Reads thresholds/timeouts from config; builds the pre-pad deque; model injectable for tests. |
| `VadEndpointer.reset()` | New listening session: clear model state, counters, buffers. |
| `VadEndpointer.process(frame)` | Feed one 512-sample frame → `VadEvent` or `None`: emits `speech_start` after `start_frames` above threshold, `timeout` if nothing within `no_speech_timeout_s`, `endpoint` after `endpoint_silence_ms` of silence or at `max_utterance_s`. |
| `VadEndpointer._finish(reason)` | Assembles the final utterance (pre-pad + buffered frames) into one `endpoint` event and resets. |

## `src/audio/wakeword.py`

**Purpose:** always-on **wake-word engine** (openWakeWord wrapper). Adds the
production behaviours raw scores lack: debounce (N consecutive frames),
cooldown (refractory period), state reset on fire, barge-in mode (raised
threshold while our own TTS plays), and input guards (int16, exactly 1280
samples).

| Member | Purpose |
|---|---|
| `WakeWordEngine.FRAME_LEN` | 1280 samples (80 ms @ 16 kHz) — what oWW's melspec pipeline is tuned for. |
| `__init__(cfg, now_fn=time.monotonic)` | Reads thresholds/debounce/cooldown from config; injectable clock makes the logic unit-testable; loads the model. |
| `_load(name_or_path)` | Loads a built-in or custom `.onnx` model; forces `inference_framework="onnx"` (tflite has no wheels on modern Windows/Python). |
| `process(frame)` → `bool` | One frame in, detection out — applies threshold (raised while speaking), debounce, cooldown, and resets model state on fire so the phrase tail can't re-trigger. |
| `set_speaking(speaking)` | Toggle barge-in mode (higher threshold while TTS is audible; never paused, or barge-in would die). |

## `src/audio/output_handler.py`

**Purpose:** speaker output with **instant kill for barge-in**. Callback-based
`OutputStream` (a blocked `write()` can't be interrupted; with a callback,
`stop()` clears the buffer and the next callback emits silence — kill latency ≈
one blocksize). Stream is persistent (open/close per utterance costs 50–200 ms
and can click); empty buffer plays silence because "buffer empty" usually means
"TTS still synthesizing", not "reply done".

| Member | Purpose |
|---|---|
| `Playback.__init__(cfg, samplerate=22050)` | Sets up the deque buffer and negotiates rate (Piper voices are 22050 Hz). |
| `_find_output(name_part)` | Resolve output device by substring (mirror of capture). |
| `_negotiate_rate()` | Ask the device for the voice's rate; if refused, build a polyphase resampler to the device default. |
| `enqueue(pcm)` | Queue int16 PCM (from TTS) for playback. |
| `end_of_utterance()` | Marks the reply as complete — the **only** way "done" can fire: the done event triggers on (ended AND buffer drained), which is the FSM's SPEAKING→IDLE trigger. |
| `chime()` | Plays the short wake-acknowledgement tone. |
| `stop()` | Hard-cut: clears everything pending (user is already talking over us). |
| `wait_done(timeout=None)` | Blocks until the reply finished playing; returns early on barge-in. |
| `playing()` | Whether audio is currently audible. |
| `close()` | Shuts the stream down for good. |
| `_callback(outdata, ...)` | PortAudio callback: drains the buffer or fills silence; detects the drained-and-ended condition. |
| `_ensure_stream()` | Lazily opens the persistent output stream. |

---

# 5. `src/asr/` — speech-to-text

## `src/asr/transcriber.py`

**Purpose:** full-featured **Whisper transcription class** with model selection,
device auto-detection, confidence scores, timestamps, batching and
context-manager support.

| Member | Purpose |
|---|---|
| `class WhisperModel(Enum)` | Available sizes: `TINY, BASE, SMALL, MEDIUM, LARGE (large-v3), LARGE_TURBO (large-v3-turbo)`. |
| `class TranscriptionResult` | Dataclass: `text`, `confidence` (0-1), `language`, `duration`, `segments` (with timings), `full_result`. |
| `Transcriber.__init__(model_name, device, language, verbose, ...)` | Stores settings, resolves the device, loads the model. |
| `_auto_detect_device()` | `"cuda"` if available else `"cpu"`. |
| `_load_model()` | Loads the Whisper weights (with warnings suppressed) and logs timing. |
| `transcribe(audio, language=None, temperature=0.0, beam_size=5)` | Main API: file path or numpy array → `TranscriptionResult`. Auto-detects language when not given. |
| `batch_transcribe(audio_files)` | Transcribes a list of files, returning a list of results (errors logged, not raised). |
| `transcribe_with_timestamps(audio)` | Returns text with per-segment `[start → end]` timing lines. |
| `_calculate_confidence(result)` | Derives a 0-1 confidence from segment `avg_logprob`s. |
| `get_supported_languages()` | Dict of the 99 language codes Whisper supports. |
| `release()` | Frees the model (and empties the CUDA cache when relevant). |
| `__enter__/__exit__` | Context-manager: auto-release. |
| `transcribe_audio(audio, model, language, device)` (module-level) | One-off convenience wrapper: builds a `Transcriber`, transcribes, releases. |

## `src/asr/processor.py`

**Purpose:** thread-safe **audio chunk processor** — a queue-based worker that
normalizes chunks and extracts features (framework for streaming ASR).

| Member | Purpose |
|---|---|
| `ASRProcessor.__init__(sample_rate=16000, chunk_size=1024, timeout=5)` | Sets up the queue, flags and transcription list. |
| `add_audio_chunk(audio_data)` | Validates and enqueues a chunk; returns success bool. |
| `process_audio()` | Worker loop: pull chunks, `_process_chunk`, collect results until stopped. |
| `_process_chunk(audio_data)` | To float32 numpy → normalize to [-1, 1] → `_extract_features`. |
| `_extract_features(audio_data)` | Feature extraction stub (energy framing) to be replaced by a real front-end. |
| `get_transcriptions()` / `clear_transcriptions()` | Read / clear accumulated results. |
| `stop_processing()` | Stops the worker loop. |
| `reset()` | Clears queue and state for reuse. |

## `src/asr/whisper_asr.py`

**Purpose:** compact **faster-whisper** engine configured from
`config/base.yaml` (`asr:` section — note: that file is not in the repo yet;
pass your own `config_path`).

| Member | Purpose |
|---|---|
| `WhisperASR.__init__(config_path="config/base.yaml")` | Reads `model_size`/`device`/`download_root` from YAML; picks `float16` (GPU) or `int8` (CPU) compute; loads the model. |
| `transcribe(audio_file_path)` → `str` | Validates the path, transcribes with `beam_size=5`, joins segments into one clean string. |

## `src/asr/exceptions.py`

**Purpose:** the ASR exception hierarchy. Base `ASRException(message, details)`
with subtrees: `AudioException` (`InvalidAudioFormatError`,
`AudioProcessingError`, `AudioQueueError`), `ModelException`
(`ModelNotFoundError`, `ModelLoadError`, `UnsupportedModelError`),
`TranscriptionException` (`TranscriptionError`, `TranscriptionTimeoutError`,
`LanguageDetectionError`), `ConfigurationException`
(`InvalidConfigurationError`, `ConfigurationFileError`) and
`ProcessingException` (`ProcessingTimeoutError`, `ProcessingStateError`,
`ProcessingError`). Each carries contextual fields (file path, model name,
timeout values…) for precise error reporting.

---

# 6. `src/nlu/` — intent detection

## `src/nlu/intent.py` 🔧

**Purpose:** Phase-1 rule-based intent detector.

| Member | Purpose |
|---|---|
| `IntentDetector.detect(transcript_text)` | Keyword match (`turn/switch/open/close/run`) → `{"intent": "COMMAND", "entities": {raw_query}}`, otherwise `{"intent": "CHAT"}`. |

`src/nlu/models/` holds the JSON intent/entity definitions (general, music,
timer, weather + patterns) for the future classifier. Other `src/nlu/*.py`
files are scaffolds 📋.

---

# 7. `src/response_generation/` — LLM replies

## `src/response_generation/llm_engine.py` 🔧

**Purpose:** generates reply text via a **local Ollama server**.

| Member | Purpose |
|---|---|
| `LLMResponseGenerator.__init__(config)` | Reads `llm:` config — provider (`ollama`), `model_name` (default `gemma2:2b-it-qat`), `base_url` (`http://localhost:11434`). |
| `generate_response(user_prompt, context="")` | POSTs to `/api/generate` (non-streaming, temperature 0.3, 10 s timeout). Maps failures to clear errors: 404 → "model not found, did you `ollama run …`?", timeout → `LLMTimeoutError`, connection refused → "is Ollama running?". |

Exceptions live in `src/response_generation/exceptions.py`:
`ResponseGenerationError` (base — provider/HTTP/connection failures),
`LLMTimeoutError` (generation exceeded the timeout) and `InvalidPromptError`.

`models/prompts.yaml`, `models/templates.yaml`, `models/llm_config.json` hold
the prompt/template data. `src/test_engine.py` is a manual test-driver for this
module (references an older `LLMConnector` name).

---

# 8. `src/storage/` — database

## `src/storage/database.py` 🔧

**Purpose:** SQLAlchemy session factory. Creates `engine` from
`DATABASE_URL` (.env) and exports `SessionLocal` for ORM sessions.

## `src/storage/models_definitions.py` 🔧

**Purpose:** ORM schema. `class ConversationLog` (`conversation_logs` table):
`id`, `timestamp`, `user_text` (ASR output), `intent` (NLU output), `response`
(read by TTS), `audio_path` (recording on disk), `processing_time_ms`.
Table creation is done externally (a `create_db.py` mentioned in comments, not
in the repo yet). The SQLite file lives at `data/database/asr.db`.

`src/storage/model/*.py` (contact, conversation, reminder, user) are scaffolds 📋.

---

# 9. `src/wake_word/` — standalone detector demo

## `src/wake_word/detector.py`

**Purpose:** self-contained **openWakeWord live demo** (script, not a module —
it runs on import!). Downloads the pre-trained models, opens a PyAudio mic
stream (16 kHz, 1280-sample chunks), prints live mic volume, and announces
detections of "hey mycroft" above a 0.1 confidence score. Ctrl-C to stop.
The production wrapper used by the pipeline is `src/audio/wakeword.py`.

---

# 10. `src/api/` and other scaffolds

## `src/api/schemas.py`

**Purpose:** Pydantic response models for the REST API: `HealthResponse`,
`ModelInfoResponse`, `TranscriptionResponse`, `StatusResponse`,
`FormatsResponse`. Used as the schema reference for `server.py` responses.

## Empty scaffolds 📋 (reserved for future phases)

`src/api/` (server, middleware, exceptions, routers: assistant/commands/
health/metrics), `src/tasks/` (executor, registry, handlers: audio/device/
knowledge/system/time), `src/utils/` (logger, decorators, validators, metrics,
helpers, device_apis), `src/tts/processor.py` + `synthesizer.py` (only
`src/tts/exceptions.py` is implemented: `TTSException`, `AudioPlaybackError`,
`SynthesisError`, `VoiceNotFoundError`, `InvalidAudioFormatError`),
`src/llm/connector.py`, `src/core/constants.py`, `src/core/orchestrator.py`,
and the remaining `src/nlu/` / `src/storage/` files.

`src/__init__.py` documents the intended package layout and public API
(`VoiceAssistant`, `Config`) in its docstring.

---

# 11. `tests/`

Run with `python -m pytest tests/`.

| File | What it tests |
|---|---|
| `sd_stub.py` | **Shared sounddevice stub** — a complete fake of the `sounddevice` module installed into `sys.modules` before audio imports. One shared stub, because per-file partial stubs break under combined test discovery. `install()` is idempotent. |
| `test_capture.py` | `Rebuffer` (frame slicing across odd chunk sizes) and `PrerollRing` (window trimming, snapshot correctness). |
| `test_vad.py` | `VadEndpointer` logic with a `FakeSilero` — speech start debounce, silence endpointing, timeouts, max-length forcing; `make()`/`frame()` are tiny factories. |
| `test_wakeword.py` | `WakeWordEngine` detection logic with a `FakeModel` and a fake clock — threshold, consecutive-frame debounce, cooldown, speaking-mode threshold. |
| `test_playback.py` | `Playback` buffering / end-of-utterance semantics by draining the callback manually (`make()`/`drain()` helpers). |
| `test_pipeline.py` | 📋 placeholder. |

---

# 12. `scripts/` and data folders

| Path | Purpose |
|---|---|
| `scripts/download_models.sh` | Downloads all pipeline models (~2.4 GB): Qwen2.5-3B-Instruct GGUF (LLM), Piper voice (TTS), Silero VAD. faster-whisper and openWakeWord fetch their own weights on first run. |
| `scripts/models/` | Where that script drops its downloads (Qwen GGUF, Piper voice, silero_vad.onnx already present). |
| `offline_models/` | Whisper weights (`small.pt`, `medium.pt`) and Piper voices (`en_US-lessac-medium`, `hi_IN-priyamvada-medium`) used by `models.py` / `whiper_test.py`. |
| `data/` | Runtime artifacts: `database/asr.db` (SQLite), `logs/`, `cache/`, `temp/`, `backups/`. |
| `output/` | Transcription output directory (`OUTPUT_DIR` in `.env`). |
| `requirements/` | Dependency splits: `base` / `dev` / `test` / `docs` / `prod`. |
| `.github/workflows/` | CI: ci-cd, code-quality, release, security-scan, test-coverage. |
| `.vscode/`, `.junie/`, `pyrefly.toml` | Editor settings, plan notes, and pyrefly type-checker config. |

---

*Generated July 7, 2026 · matches project state as of this date.*
