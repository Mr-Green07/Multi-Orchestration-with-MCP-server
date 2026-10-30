# MainProject Overview

## Project Structure

- **src/**: Core source code.
  - **api/**: API endpoints and routers.
    - **routers/**: Individual router modules (assistant.py, commands.py, health.py, metrics.py, etc.).
  - **asr/**: Automatic Speech Recognition.
    - **processor.py**, **transcriber.py**, **whisper_asr.py**.
  - **audio/**: Audio capture and processing.
    - **capture.py**, **vad.py**, **wakeword.py**, **output_handler.py**.
  - **core/**: Core utilities and logic.
    - **config.py**, **constants.py**, **events.py**, **orchestrator.py**, **pipeline.py**, **state.py**.
  - **llm/**: Large Language Model integration.
    - **connector.py**, **llm_engine.py**, **template_engine.py**.
  - **memory/**: Memory management.
  - **nlu/**: Natural Language Understanding.
    - **entity_extractor.py**, **intent_classifier.py**, **intent.py**, **preprocessor.py**.
  - **response_generation/**: Response generation.
    - **formatter.py**, **llm_engine.py**, **template_engine.py**.
  - **router/**: Routing logic.
  - **storage/**: Persistent storage.
    - **database.py**, **encryption.py**, **models_definitions.py**, **models.py**, **migrations/**.
  - **tts/**: Text-to-Speech.
    - **processor.py**, **synthesizer.py**.
  - **wake_word/**: Wake word detection.
    - **detector.py**, **utils.py**.
- **frontend/**: Frontend assets (app.js, index.html, styles.css).
- **offline_models/**: Offline model files.
- **data/**: Data directories (backups, cache, database, logs, models, temp).
- **output/**: Output logs and artifacts.
- **scripts/**: Helper scripts (download_models.sh).
- **tests/**: Test files.

## Key Concepts

1. **Orchestration** – The `orchestrator.py` in `core/` coordinates the overall workflow, managing state and pipeline execution.
2. **Audio Pipeline** – `audio/` handles capture, VAD (voice activity detection), wake word detection, and audio preprocessing.
3. **ASR** – `asr/` provides speech-to-text conversion using Whisper or similar models.
4. **NLU** – `nlu/` interprets user intent and extracts entities from transcribed text.
5. **LLM Integration** – `llm/` and `response_generation/` handle communication with language models, prompt templating, and response formatting.
6. **Storage** – `storage/` manages persistent data, including database interactions, encryption, and model storage.
7. **TTS** – `tts/` converts generated text back to speech.
8. **API Layer** – `api/` exposes REST endpoints for client interaction, with routers handling specific functionalities.
9. **Configuration** – `config.yaml` and `core/config.py` provide project configuration and constants.
10. **Testing** – `tests/` contains unit and integration tests for various components.

## Module Responsibilities

- **core/config.py**: Holds configuration settings, constants, and environment variables.
- **core/orchestrator.py**: Coordinates the main pipeline, managing state transitions and task execution.
- **core/pipeline.py**: Defines the step-by-step processing pipeline (e.g., capture → VAD → ASR → NLU → LLM).
- **audio/capture.py**: Captures audio from microphone or file input.
- **audio/vad.py**: Implements voice activity detection to filter silent segments.
- **audio/wakeword.py**: Detects wake word to activate the system.
- **audio/output_handler.py**: Handles output routing (e.g., speaker, file).
- **asr/processor.py**: Processes raw audio into features for ASR.
- **asr/transcriber.py**: Uses Whisper or other ASR models to transcribe audio.
- **asr/whisper_asr.py**: Specific Whisper integration.
- **nlu/intent_classifier.py**: Classifies user intent.
- **nlu/entity_extractor.py**: Extracts relevant entities from text.
- **nlu/preprocessor.py**: Preprocesses transcribed text for NLU.
- **llm/connector.py**: Manages connection to LLM services.
- **llm/llm_engine.py**: Core logic for generating responses.
- **response_generation/formatter.py**: Formats final responses for output.
- **tts/processor.py**: Prepares text for speech synthesis.
- **tts/synthesizer.py**: Generates speech from text.
- **storage/database.py**: Interacts with the database (e.g., storing logs, models).
- **storage/encryption.py**: Handles encryption/decryption of sensitive data.
- **frontend/**: Provides the UI assets (HTML/JS/CSS) for client-side interaction.

## Data Flow

1. **Audio Capture** – `audio/capture.py` records audio.
2. **VAD & Wake Word** – `audio/vad.py` and `audio/wakeword.py` filter and activate.
3. **ASR** – `asr/whisper_asr.py` transcribes audio to text.
4. **NLU** – `nlu/preprocessor.py` → `nlu/intent_classifier.py` → `nlu/entity_extractor.py` interpret intent and entities.
5. **LLM** – `llm/connector.py` sends context to LLM; `llm/llm_engine.py` processes response.
6. **Response Generation** – `response_generation/formatter.py` shapes the output.
7. **TTS** – `tts/synthesizer.py` converts text to speech if needed.
8. **Storage** – Relevant data (logs, models) are stored/retrieved via `storage/database.py`.

## Configuration

- Central configuration is defined in `config.yaml` and loaded via `core/config.py`.
- Environment-specific settings (dev, test, prod) are managed through `requirements/` files.

## Next Steps

- Review the `README.md` for project-specific setup instructions.
- Explore the `src/` directory to understand implementation details.
- Run `python -m pip install -r requirement.txt` to install dependencies.
- Execute `python main.py` to start the server.