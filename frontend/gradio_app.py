"""Gradio-based frontend for the Offline ASR system.

Replaces the JavaScript/HTML/CSS frontend with a pure-Python UI.
Calls the Whisper model manager directly (in-process, no HTTP needed),
passes the query through NLU -> Task Executor -> LLM Engine -> TTS,
and displays both the transcribed user query and the assistant's answer.

Run standalone:
    python frontend/gradio_app.py

Or via the desktop launcher:
    python frontend/desktop.py
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from pathlib import Path

# Make project root importable regardless of where this is launched from
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import gradio as gr  # type: ignore # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- Model & Brain Glue
try:
    # pyrefly: ignore [missing-import]
    from models import get_model_manager  # noqa: E402
    _MODELS_AVAILABLE = True
except Exception as _exc:
    _MODELS_AVAILABLE = False
    _MODELS_ERROR = str(_exc)

try:
    # pyrefly: ignore [missing-import]
    from src.nlu.preprocessor import TextPreprocessor
    # pyrefly: ignore [missing-import]
    from src.nlu.intent_classifier import IntentClassifier
    # pyrefly: ignore [missing-import]
    from src.nlu.entity_extractor import EntityExtractor
    # pyrefly: ignore [missing-import]
    from src.tasks.executor import TaskExecutor
    # pyrefly: ignore [missing-import]
    import src.tasks.handlers
    # pyrefly: ignore [missing-import]
    from src.response_generation.llm_engine import LLMResponseGenerator
    # pyrefly: ignore [missing-import]
    from src.utils.helpers import safe_read_yaml
    # pyrefly: ignore [missing-import]
    from src.core.constants import ROOT_DIR

    cfg_path = ROOT_DIR / "config.yaml"
    cfg = safe_read_yaml(cfg_path) if cfg_path.exists() else {}

    _preprocessor = TextPreprocessor()
    _classifier = IntentClassifier()
    _extractor = EntityExtractor()
    _task_executor = TaskExecutor()
    _llm_generator = LLMResponseGenerator()

    # Optional TTS initialization
    try:
        # pyrefly: ignore [missing-import]
        from src.tts.synthesizer import TTSSynthesizer
        _tts = TTSSynthesizer(cfg)
    except Exception:
        _tts = None

    _ASSISTANT_AVAILABLE = True
    _ASSISTANT_ERROR = ""
except Exception as _assistant_exc:
    _ASSISTANT_AVAILABLE = False
    _ASSISTANT_ERROR = str(_assistant_exc)


def _model_info() -> dict:
    """Return a dict describing the current Whisper model."""
    if not _MODELS_AVAILABLE:
        return {
            "model_size": os.getenv("MODEL_SIZE", "small"),
            "device": os.getenv("DEVICE", "cpu"),
            "language": os.getenv("LANGUAGE", "en"),
            "model_loaded": False,
            "error": f"whisper not installed: {_MODELS_ERROR}",
        }
    return get_model_manager().get_model_info()


def _model_info_md() -> str:
    """Format model info as a Markdown table for display."""
    info = _model_info()
    rows = [
        ("Whisper Model", info.get("model_size", "?")),
        ("Device", info.get("device", "?")),
        ("Language", info.get("language", "auto")),
        ("Loaded", "✅ Yes" if info.get("model_loaded") else "⏳ On first use"),
        ("Assistant Engine", "✅ Active (Ollama/Gemma)" if _ASSISTANT_AVAILABLE else f"⚠️ {_ASSISTANT_ERROR}"),
    ]
    if info.get("error"):
        rows.append(("Status", f"⚠️ {info['error']}"))
    md = "| Property | Value |\n|----------|-------|\n"
    md += "\n".join(f"| {k} | {v} |" for k, v in rows)
    return md


# ------------------------------------------------------------ Core Processing
SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}


def process_voice_and_answer(audio_path: str | None) -> tuple[str, str, str | None, str, str]:
    """Transcribe user audio, query the NLU+LLM assistant engine, and synthesize response.

    Returns:
        (user_transcript, assistant_answer, audio_reply_path, language_chip, meta_line)
    """
    if audio_path is None:
        return (
            "No audio provided. Record via microphone or upload an audio file.",
            "Please record your voice or speak a command to start.",
            None,
            "—",
            "",
        )

    suffix = Path(audio_path).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        return (
            f"Unsupported format '{suffix}'. Allowed: {', '.join(sorted(SUPPORTED_FORMATS))}",
            "Invalid file format.",
            None,
            "—",
            "",
        )

    started = time.perf_counter()

    # 1. Speech-to-Text (STT) via Whisper
    if _MODELS_AVAILABLE:
        manager = get_model_manager()
        model = manager.load_model()
        result = model.transcribe(audio_path, language=manager.language or None)
        user_text = (result.get("text") or "").strip()
        detected = result.get("language", manager.language or "auto")
        segments = result.get("segments") or []
        duration = float(segments[-1]["end"]) if segments else 0.0
    else:
        user_text = "Hello, what can you do?"
        detected, duration = "en", 1.5

    if not user_text:
        return (
            "(No speech detected in audio recording)",
            "I couldn't hear any clear words. Please try speaking again.",
            None,
            detected,
            "0.0s audio",
        )

    # 2. Assistant Processing (NLU -> Task Executor -> LLM Response Generator)
    if _ASSISTANT_AVAILABLE:
        try:
            normalized = _preprocessor.process(user_text)
            intent = _classifier.classify(normalized)
            intent.raw_text = user_text

            expected = intent.entities if hasattr(intent, "entities") else []
            extracted_entities = _extractor.extract(normalized, expected)
            for k, v in extracted_entities.items():
                intent.entities[k] = v

            task_result = _task_executor.execute(intent)
            assistant_answer = _llm_generator.generate_response(intent, task_result, stream=False)
        except Exception as exc:
            logger.error("Assistant generation failed: %s", exc)
            assistant_answer = f"I understood: '{user_text}', but encountered an issue generating a full response ({exc})."
    else:
        assistant_answer = f"Received query: '{user_text}'. (Assistant pipeline currently unavailable)"

    # 3. Text-to-Speech (TTS) Synthesis (Optional)
    tts_wav_path = None
    if _tts and assistant_answer:
        try:
            tmp_fd, tts_wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(tmp_fd)
            _tts._engine.save_to_file(assistant_answer, tts_wav_path)
            _tts._engine.runAndWait()
        except Exception as tts_err:
            logger.warning("TTS generation error: %s", tts_err)
            tts_wav_path = None

    elapsed = time.perf_counter() - started
    meta = f"{duration:.1f}s audio · {elapsed:.2f}s total processing"

    return user_text, assistant_answer, tts_wav_path, detected, meta


# --------------------------------------------------------------- Gradio UI
CUSTOM_CSS = """
:root {
    --body-background-fill: #0b0f19 !important;
    --background-fill-primary: rgba(255,255,255,0.06) !important;
    --background-fill-secondary: rgba(255,255,255,0.04) !important;
    --block-background-fill: rgba(15, 23, 42, 0.75) !important;
    --block-border-color: rgba(255,255,255,0.12) !important;
    --block-label-text-color: #e2e8f0 !important;
    --body-text-color: #f8fafc !important;
    --body-text-color-subdued: #94a3b8 !important;
    --input-background-fill: rgba(0,0,0,0.3) !important;
    --color-accent: #6366f1 !important;
    --button-primary-background-fill: linear-gradient(135deg, #6366f1, #a855f7) !important;
    --button-primary-text-color: #ffffff !important;
}

.gradio-container {
    max-width: 1000px !important;
    margin: auto !important;
    font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

#brand-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 0;
}
#brand-header .brand-dot {
    width: 16px; height: 16px;
    border-radius: 50%;
    background: linear-gradient(135deg, #6366f1, #ec4899);
    box-shadow: 0 0 16px #6366f1;
}
#brand-header h1 {
    font-size: 22px;
    font-weight: 700;
    margin: 0;
    color: #f8fafc;
}

.lang-chip {
    display: inline-block;
    font-size: 13px;
    padding: 4px 12px;
    border-radius: 999px;
    background: rgba(99, 102, 241, 0.2);
    color: #a5b4fc;
    border: 1px solid rgba(99, 102, 241, 0.4);
    font-weight: 600;
}

.meta-text {
    font-size: 13px;
    color: #94a3b8;
}

#user-output textarea {
    font-size: 15px !important;
    color: #cbd5e1 !important;
}

#assistant-output textarea {
    font-size: 16px !important;
    font-weight: 600 !important;
    color: #38bdf8 !important;
}
"""


def build_ui() -> gr.Blocks:
    """Build and return the Gradio Blocks UI."""
    with gr.Blocks(title="Antigravity Voice Assistant Console") as app:
        # Header
        gr.HTML(
            '<div id="brand-header">'
            '  <span class="brand-dot"></span>'
            "  <h1>Antigravity&nbsp;Voice&nbsp;Assistant</h1>"
            "</div>"
        )

        with gr.Row(equal_height=False):
            # Left column: Speech input & Conversation display
            with gr.Column(scale=3):
                gr.Markdown("### 🎙️ Speak to Assistant")

                audio_input = gr.Audio(
                    sources=["microphone", "upload"],
                    type="filepath",
                    label="Record or upload audio question",
                    show_label=True,
                )

                submit_btn = gr.Button(
                    "⚡ Process & Answer",
                    variant="primary",
                    size="lg",
                )

                gr.Markdown("### 💬 Conversation")

                user_transcript_out = gr.Textbox(
                    label="🗣️ Your Query (Transcribed)",
                    lines=3,
                    interactive=False,
                    elem_id="user-output",
                    placeholder="Your spoken query will appear here...",
                )

                assistant_answer_out = gr.Textbox(
                    label="🤖 Assistant Answer",
                    lines=5,
                    interactive=False,
                    elem_id="assistant-output",
                    placeholder="The AI assistant's answer will appear here...",
                )

                audio_reply_out = gr.Audio(
                    label="🔊 Assistant Voice Response (TTS)",
                    interactive=False,
                    autoplay=True,
                )

                with gr.Row():
                    lang_out = gr.HTML('<span class="lang-chip">auto</span>')
                    meta_out = gr.HTML('<span class="meta-text"></span>')

            # Right column: System info
            with gr.Column(scale=1, min_width=250):
                gr.Markdown("### ⚙️ System Status")
                engine_info = gr.Markdown(
                    value=_model_info_md(),
                    elem_id="engine-info",
                )
                refresh_btn = gr.Button("↻ Refresh Status", size="sm")

        # Event wiring
        def on_process(audio_path):
            user_txt, ans_txt, audio_path_out, lang, meta = process_voice_and_answer(audio_path)
            lang_html = f'<span class="lang-chip">{lang}</span>'
            meta_html = f'<span class="meta-text">{meta}</span>'
            return user_txt, ans_txt, audio_path_out, lang_html, meta_html

        submit_btn.click(
            fn=on_process,
            inputs=[audio_input],
            outputs=[user_transcript_out, assistant_answer_out, audio_reply_out, lang_out, meta_out],
        )

        audio_input.stop_recording(
            fn=on_process,
            inputs=[audio_input],
            outputs=[user_transcript_out, assistant_answer_out, audio_reply_out, lang_out, meta_out],
        )

        refresh_btn.click(fn=_model_info_md, inputs=[], outputs=[engine_info])

    return app


# ---------------------------------------------------------------- Entry point
GRADIO_PORT_ENV = os.getenv("GRADIO_PORT")
PORT = int(GRADIO_PORT_ENV) if GRADIO_PORT_ENV else 7860


def launch(**kwargs) -> None:
    """Build the Gradio app and launch it."""
    defaults = dict(
        server_name="0.0.0.0",
        server_port=PORT,
        share=False,
        inbrowser=True,
        css=CUSTOM_CSS,
    )
    defaults.update(kwargs)
    app = build_ui()
    try:
        app.launch(**defaults)
    except OSError:
        # Fallback if preferred port is busy: let Gradio automatically select an available port
        logger.warning("Port %s is in use, searching for an open port...", PORT)
        defaults.pop("server_port", None)
        app.launch(**defaults)


if __name__ == "__main__":
    launch()
