#!/usr/bin/env python3
"""
Offline ASR Voice Assistant — Gradio Glass-Design Floating Desktop App
Features: Rich dashboard with sidebar, mic button, transcript, waveform,
           model card, status, controls — dark glassmorphism theme.
"""

import gradio as gr
import numpy as np
import time
import json
import os
import threading
from datetime import datetime

# ──────────────────────────────────────────────
# CUSTOM CSS — Dark Glassmorphism Theme
# ──────────────────────────────────────────────
GLASS_CSS = """
/* ── ROOT / GLOBAL ── */
:root {
    --glass-bg: rgba(15, 15, 30, 0.65);
    --glass-border: rgba(255, 255, 255, 0.08);
    --glass-highlight: rgba(255, 255, 255, 0.12);
    --accent-cyan: #00d4ff;
    --accent-green: #00ff88;
    --accent-orange: #ff8800;
    --accent-red: #ff4444;
    --accent-purple: #bb86fc;
    --text-primary: #e0e0e0;
    --text-secondary: #a0a0b0;
    --bg-gradient: linear-gradient(135deg, #0a0a1a 0%, #1a0a2e 25%, #0a1a2e 50%, #1a1a3a 75%, #0a0a1a 100%);
    --shadow-glow: 0 0 20px rgba(0, 212, 255, 0.15), 0 0 40px rgba(0, 212, 255, 0.05);
}

/* ── BODY / MAIN CONTAINER ── */
body, .gradio-container {
    background: var(--bg-gradient) !important;
    background-size: 400% 400% !important;
    animation: gradientShift 15s ease infinite !important;
    min-height: 100vh !important;
    color: var(--text-primary) !important;
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif !important;
}

@keyframes gradientShift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

.gradio-container {
    max-width: 100% !important;
    padding: 0 !important;
    margin: 0 !important;
}

/* ── GLASS PANELS ── */
.glass-panel {
    background: var(--glass-bg) !important;
    backdrop-filter: blur(24px) !important;
    -webkit-backdrop-filter: blur(24px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 16px !important;
    box-shadow: var(--shadow-glow) !important;
    padding: 20px !important;
    transition: all 0.3s ease !important;
}

.glass-panel:hover {
    border-color: rgba(0, 212, 255, 0.15) !important;
    box-shadow: 0 0 30px rgba(0, 212, 255, 0.2), 0 0 60px rgba(0, 212, 255, 0.08) !important;
}

/* ── SIDEBAR ── */
.sidebar-panel {
    background: rgba(10, 10, 25, 0.8) !important;
    backdrop-filter: blur(30px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 16px !important;
    box-shadow: var(--shadow-glow) !important;
    padding: 16px !important;
    min-height: 100% !important;
}

/* ── ALL GRADIO BLOCKS ── */
.gr-box, .gr-panel, .gr-input, .gr-group, .gr-column, .gr-row,
.block, .containing-block {
    background: var(--glass-bg) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 12px !important;
    color: var(--text-primary) !important;
}

/* ── TABS ── */
.gr-tab-label, .tab-nav .tab-label {
    color: var(--text-secondary) !important;
    background: transparent !important;
    border: none !important;
    font-weight: 500 !important;
    transition: all 0.3s ease !important;
}

.gr-tab-label.selected, .tab-nav .tab-label.selected {
    color: var(--accent-cyan) !important;
    background: rgba(0, 212, 255, 0.1) !important;
    border-bottom: 2px solid var(--accent-cyan) !important;
}

.tab-nav {
    background: rgba(10, 10, 25, 0.6) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 12px 12px 0 0 !important;
}

/* ── HEADINGS ── */
h1, h2, h3, h4, h5 {
    color: var(--text-primary) !important;
    font-weight: 600 !important;
}

.title-text {
    font-size: 1.6em !important;
    color: var(--accent-cyan) !important;
    text-shadow: 0 0 10px rgba(0, 212, 255, 0.3) !important;
    letter-spacing: 0.5px !important;
}

.subtitle-text {
    font-size: 0.9em !important;
    color: var(--text-secondary) !important;
}

/* ── BUTTONS ── */
.gr-button, button {
    background: rgba(0, 212, 255, 0.15) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid rgba(0, 212, 255, 0.25) !important;
    border-radius: 10px !important;
    color: var(--accent-cyan) !important;
    font-weight: 500 !important;
    transition: all 0.3s ease !important;
    cursor: pointer !important;
}

.gr-button:hover, button:hover {
    background: rgba(0, 212, 255, 0.3) !important;
    border-color: var(--accent-cyan) !important;
    box-shadow: 0 0 15px rgba(0, 212, 255, 0.4) !important;
    transform: translateY(-1px) !important;
}

.gr-button:active, button:active {
    transform: translateY(0px) !important;
    box-shadow: 0 0 10px rgba(0, 212, 255, 0.3) !important;
}

/* ── MIC BUTTON (PRIMARY) ── */
.mic-button {
    background: rgba(0, 212, 255, 0.2) !important;
    border: 2px solid rgba(0, 212, 255, 0.4) !important;
    border-radius: 50% !important;
    width: 80px !important;
    height: 80px !important;
    min-width: 80px !important;
    min-height: 80px !important;
    font-size: 2em !important;
    color: var(--accent-cyan) !important;
    box-shadow: 0 0 25px rgba(0, 212, 255, 0.3), 0 0 50px rgba(0, 212, 255, 0.1) !important;
    transition: all 0.3s ease !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    cursor: pointer !important;
    position: relative !important;
}

.mic-button:hover {
    background: rgba(0, 212, 255, 0.35) !important;
    border-color: var(--accent-cyan) !important;
    box-shadow: 0 0 35px rgba(0, 212, 255, 0.5), 0 0 70px rgba(0, 212, 255, 0.2) !important;
    transform: scale(1.05) !important;
}

.mic-button.recording {
    background: rgba(255, 68, 68, 0.25) !important;
    border-color: var(--accent-red) !important;
    color: var(--accent-red) !important;
    box-shadow: 0 0 25px rgba(255, 68, 68, 0.4), 0 0 50px rgba(255, 68, 68, 0.15) !important;
    animation: pulseRecord 1.5s ease-in-out infinite !important;
}

@keyframes pulseRecord {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.08); }
}

/* ── STATUS INDICATORS ── */
.status-dot {
    width: 10px !important;
    height: 10px !important;
    border-radius: 50% !important;
    display: inline-block !important;
    margin-right: 8px !important;
}

.status-online  { background: var(--accent-green) !important; box-shadow: 0 0 8px var(--accent-green) !important; }
.status-offline { background: var(--accent-red) !important;   box-shadow: 0 0 8px var(--accent-red) !important; }
.status-loading { background: var(--accent-orange) !important; box-shadow: 0 0 8px var(--accent-orange) !important; animation: blink 1s infinite !important; }

@keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
}

/* ── CHAT / TRANSCRIPT AREA ── */
.chat-container {
    background: rgba(5, 5, 15, 0.5) !important;
    backdrop-filter: blur(16px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 14px !important;
    padding: 16px !important;
    min-height: 350px !important;
    max-height: 500px !important;
    overflow-y: auto !important;
}

.chat-message-user {
    background: rgba(0, 212, 255, 0.1) !important;
    border: 1px solid rgba(0, 212, 255, 0.15) !important;
    border-radius: 12px 12px 4px 12px !important;
    padding: 10px 14px !important;
    margin: 8px 0 !important;
    color: var(--text-primary) !important;
    text-align: right !important;
    max-width: 80% !important;
    float: right !important;
    clear: both !important;
}

.chat-message-assistant {
    background: rgba(187, 134, 252, 0.1) !important;
    border: 1px solid rgba(187, 134, 252, 0.15) !important;
    border-radius: 12px 12px 12px 4px !important;
    padding: 10px 14px !important;
    margin: 8px 0 !important;
    color: var(--text-primary) !important;
    text-align: left !important;
    max-width: 80% !important;
    float: left !important;
    clear: both !important;
}

.chat-message-system {
    background: rgba(255, 136, 0, 0.08) !important;
    border: 1px solid rgba(255, 136, 0, 0.12) !important;
    border-radius: 8px !important;
    padding: 6px 10px !important;
    margin: 4px 0 !important;
    color: var(--accent-orange) !important;
    text-align: center !important;
    font-size: 0.85em !important;
    clear: both !important;
}

/* ── MODEL CARD ── */
.model-card {
    background: rgba(10, 10, 25, 0.7) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(187, 134, 252, 0.2) !important;
    border-radius: 14px !important;
    padding: 16px !important;
    box-shadow: 0 0 15px rgba(187, 134, 252, 0.1) !important;
}

.model-card-title {
    color: var(--accent-purple) !important;
    font-size: 1.1em !important;
    font-weight: 600 !important;
    text-shadow: 0 0 8px rgba(187, 134, 252, 0.3) !important;
}

.model-card-value {
    color: var(--accent-green) !important;
    font-weight: 500 !important;
}

/* ── WAVEFORM ── */
.waveform-panel {
    background: rgba(5, 5, 15, 0.6) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(0, 255, 136, 0.12) !important;
    border-radius: 12px !important;
    padding: 12px !important;
}

/* ── INPUT / TEXTBOX ── */
.gr-text-input, .gr-input-text, input[type="text"], textarea {
    background: rgba(15, 15, 30, 0.5) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
    caret-color: var(--accent-cyan) !important;
}

.gr-text-input:focus, input:focus, textarea:focus {
    border-color: rgba(0, 212, 255, 0.3) !important;
    box-shadow: 0 0 15px rgba(0, 212, 255, 0.2) !important;
}

/* ── DROPDOWN ── */
.gr-dropdown, select {
    background: rgba(15, 15, 30, 0.5) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
}

/* ── SLIDER ── */
.gr-slider input[type="range"] {
    background: rgba(0, 212, 255, 0.1) !important;
    border-radius: 4px !important;
}

/* ── FILE UPLOAD ── */
.gr-file-upload {
    background: rgba(15, 15, 30, 0.4) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px dashed rgba(0, 212, 255, 0.2) !important;
    border-radius: 12px !important;
    color: var(--text-secondary) !important;
}

.gr-file-upload:hover {
    border-color: var(--accent-cyan) !important;
    background: rgba(0, 212, 255, 0.05) !important;
}

/* ── SCROLLBAR ── */
::-webkit-scrollbar {
    width: 6px !important;
    height: 6px !important;
}
::-webkit-scrollbar-track {
    background: rgba(15, 15, 30, 0.3) !important;
    border-radius: 3px !important;
}
::-webkit-scrollbar-thumb {
    background: rgba(0, 212, 255, 0.2) !important;
    border-radius: 3px !important;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(0, 212, 255, 0.4) !important;
}

/* ── PROGRESS BAR ── */
.gr-progress-bar {
    background: rgba(0, 212, 255, 0.1) !important;
    border-radius: 4px !important;
}
.gr-progress-bar-fill {
    background: linear-gradient(90deg, var(--accent-cyan), var(--accent-green)) !important;
    border-radius: 4px !important;
}

/* ── LABEL ── */
.gr-label, label {
    color: var(--text-secondary) !important;
    font-size: 0.85em !important;
}

/* ── BADGE / TAG ── */
.badge {
    display: inline-block !important;
    padding: 2px 8px !important;
    border-radius: 6px !important;
    font-size: 0.75em !important;
    font-weight: 500 !important;
}

.badge-online  { background: rgba(0, 255, 136, 0.15); color: var(--accent-green); border: 1px solid rgba(0, 255, 136, 0.2); }
.badge-offline { background: rgba(255, 68, 68, 0.15); color: var(--accent-red); border: 1px solid rgba(255, 68, 68, 0.2); }
.badge-model   { background: rgba(187, 134, 252, 0.15); color: var(--accent-purple); border: 1px solid rgba(187, 134, 252, 0.2); }

/* ── ANIMATED PARTICLES BG ── */
.particle-bg {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100% !important;
    height: 100% !important;
    z-index: -1 !important;
    overflow: hidden !important;
    pointer-events: none !important;
}

/* ── FLOATING WINDOW EFFECT ── */
.floating-window {
    position: relative !important;
    margin: 10px auto !important;
    max-width: 960px !important;
    border-radius: 20px !important;
    overflow: hidden !important;
}

/* ── TOGGLE / SWITCH ── */
.gr-checkbox, .gr-switch {
    color: var(--text-primary) !important;
}

/* ── FOOTER ── */
.footer-glass {
    background: rgba(10, 10, 25, 0.6) !important;
    backdrop-filter: blur(16px) !important;
    border-top: 1px solid var(--glass-border) !important;
    padding: 8px 16px !important;
    text-align: center !important;
    color: var(--text-secondary) !important;
    font-size: 0.8em !important;
}

/* ── RESPONSIVE ── */
@media (max-width: 768px) {
    .floating-window { max-width: 100% !important; }
    .mic-button { width: 60px !important; height: 60px !important; min-width: 60px !important; min-height: 60px !important; }
}
"""

# ──────────────────────────────────────────────
# STATE & SIMULATION
# ──────────────────────────────────────────────
conversation_history = []
is_recording = False
recording_start_time = None

# Simulated system status
SYSTEM_STATUS = {
    "whisper_model": "small",
    "device": "cpu",
    "language": "en",
    "llm_status": "Online (Ollama gemma2:2b)",
    "tts_status": "Online (pyttsx3)",
    "vad_status": "Active (Silero VAD v5)",
    "wake_word": "Listening (openWakeWord)",
    "pipeline_state": "IDLE",
    "uptime": "0h 0m",
    "transcriptions": 0,
    "api_port": 8000,
}

# pyrefly: ignore [missing-import]
import pandas as pd

# Simulated waveform data (pandas.DataFrame required by gr.LinePlot)
def generate_waveform_data(duration=3, num_points=100):
    t = np.linspace(0, duration, num_points)
    signal = 0.3 * np.sin(2 * np.pi * 3 * t) + 0.1 * np.sin(2 * np.pi * 6 * t) + 0.5
    noise = np.random.normal(0, 0.05, len(t))
    return pd.DataFrame({"time": t, "amplitude": signal + noise})


# ──────────────────────────────────────────────
# LOGIC FUNCTIONS
# ──────────────────────────────────────────────
def start_recording():
    """Simulate starting mic recording"""
    global is_recording, recording_start_time
    is_recording = True
    recording_start_time = time.time()
    SYSTEM_STATUS["pipeline_state"] = "LISTENING"
    status_html = build_status_html()
    return (
        "🔴 RECORDING...",       # mic status label
        status_html,              # status panel
        gr.update(value=generate_waveform_data(), visible=True),  # waveform
    )


def stop_recording():
    """Simulate stopping recording and transcribing"""
    global is_recording, recording_start_time
    is_recording = False
    duration = time.time() - recording_start_time if recording_start_time else 2.0
    recording_start_time = None
    SYSTEM_STATUS["pipeline_state"] = "THINKING"
    SYSTEM_STATUS["transcriptions"] += 1

    # Simulated transcript
    simulated_transcript = "Hello, what's the weather like in Ludhiana today?"
    simulated_response = "In Ludhiana, it's currently 32 degrees Celsius with partly cloudy skies and 65% humidity. You might want to carry an umbrella as there's a 30% chance of rain this evening."

    # Add to conversation
    conversation_history.append({
        "role": "user",
        "content": simulated_transcript,
        "time": datetime.now().strftime("%H:%M:%S")
    })
    conversation_history.append({
        "role": "assistant",
        "content": simulated_response,
        "time": datetime.now().strftime("%H:%M:%S")
    })

    SYSTEM_STATUS["pipeline_state"] = "IDLE"
    chat_html = build_chat_html()
    status_html = build_status_html()

    return (
        "🎤 Tap to Record",     # mic status label
        chat_html,               # transcript panel
        status_html,             # status panel
        simulated_transcript,    # raw transcript text
        simulated_response,      # response text
        gr.update(visible=False),# waveform hide
        f"{duration:.1f}s",      # duration display
    )


def send_text_message(text):
    """Handle text input from the user"""
    if not text.strip():
        return build_chat_html(), build_status_html(), "", ""

    SYSTEM_STATUS["pipeline_state"] = "THINKING"
    SYSTEM_STATUS["transcriptions"] += 1

    # Simulated response based on input
    responses = {
        "weather": "In Ludhiana, it's 32°C, partly cloudy, humidity 65%.",
        "time": f"The current time is {datetime.now().strftime('%I:%M %p')}.",
        "timer": "Timer set for 5 minutes. I'll remind you when it's done.",
        "music": "Playing your favorite playlist on Spotify.",
        "default": f"I understand you said: '{text}'. Let me think about that... Based on my analysis, I'd recommend checking the local resources for more information."
    }

    # Simple keyword matching for demo
    response = responses["default"]
    for key in responses:
        if key != "default" and key in text.lower():
            response = responses[key]
            break

    conversation_history.append({
        "role": "user",
        "content": text,
        "time": datetime.now().strftime("%H:%M:%S")
    })
    conversation_history.append({
        "role": "assistant",
        "content": response,
        "time": datetime.now().strftime("%H:%M:%S")
    })

    SYSTEM_STATUS["pipeline_state"] = "IDLE"
    return build_chat_html(), build_status_html(), "", response


def upload_audio_file(file):
    """Handle audio file upload"""
    if file is None:
        return build_chat_html(), build_status_html(), "", "No file uploaded"

    filename = os.path.basename(file) if isinstance(file, str) else "uploaded_audio"
    SYSTEM_STATUS["pipeline_state"] = "PROCESSING"
    SYSTEM_STATUS["transcriptions"] += 1

    simulated_transcript = f"[Transcribed from {filename}]: This is a simulated transcription of the uploaded audio file."
    simulated_response = "I've processed your audio file. The transcription is ready. Would you like me to do anything specific with this content?"

    conversation_history.append({
        "role": "system",
        "content": f"📎 File uploaded: {filename}",
        "time": datetime.now().strftime("%H:%M:%S")
    })
    conversation_history.append({
        "role": "user",
        "content": simulated_transcript,
        "time": datetime.now().strftime("%H:%M:%S")
    })
    conversation_history.append({
        "role": "assistant",
        "content": simulated_response,
        "time": datetime.now().strftime("%H:%M:%S")
    })

    SYSTEM_STATUS["pipeline_state"] = "IDLE"
    return build_chat_html(), build_status_html(), simulated_transcript, simulated_response


def update_model_config(model_size, device, language):
    """Update model configuration"""
    SYSTEM_STATUS["whisper_model"] = model_size
    SYSTEM_STATUS["device"] = device
    SYSTEM_STATUS["language"] = language
    return build_status_html(), build_model_card_html()


def clear_conversation():
    """Clear chat history"""
    conversation_history.clear()
    SYSTEM_STATUS["transcriptions"] = 0
    return build_chat_html(), build_status_html(), "", ""


# ──────────────────────────────────────────────
# HTML BUILDERS
# ──────────────────────────────────────────────
def build_chat_html():
    """Build glass-styled chat HTML from conversation history"""
    if not conversation_history:
        return """
        <div class="chat-container" style="display:flex;align-items:center;justify-content:center;height:350px;">
            <div style="text-align:center;color:#a0a0b0;">
                <div style="font-size:2.5em;margin-bottom:10px;">🎤</div>
                <div style="font-size:1.1em;">Tap the microphone or type a message</div>
                <div style="font-size:0.85em;margin-top:6px;color:#606070;">Or upload an audio file to transcribe</div>
            </div>
        </div>
        """

    messages_html = ""
    for msg in conversation_history:
        role = msg["role"]
        content = msg["content"]
        time_str = msg["time"]

        if role == "user":
            messages_html += f"""
            <div class="chat-message-user">
                <div style="font-size:0.75em;color:#00d4ff;margin-bottom:3px;">You · {time_str}</div>
                <div>{content}</div>
            </div>
            <div style="clear:both;"></div>
            """
        elif role == "assistant":
            messages_html += f"""
            <div class="chat-message-assistant">
                <div style="font-size:0.75em;color:#bb86fc;margin-bottom:3px;">Assistant · {time_str}</div>
                <div>{content}</div>
            </div>
            <div style="clear:both;"></div>
            """
        elif role == "system":
            messages_html += f"""
            <div class="chat-message-system">{content}</div>
            <div style="clear:both;"></div>
            """

    return f"""
    <div class="chat-container">
        {messages_html}
    </div>
    """


def build_status_html():
    """Build glass-styled status panel HTML"""
    state_colors = {
        "IDLE": "#a0a0b0",
        "LISTENING": "#00ff88",
        "THINKING": "#ff8800",
        "SPEAKING": "#bb86fc",
        "PROCESSING": "#00d4ff",
        "REASONING": "#ff4444",
    }
    state_color = state_colors.get(SYSTEM_STATUS["pipeline_state"], "#a0a0b0")

    return f"""
    <div class="glass-panel" style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <span style="font-size:1em;font-weight:600;color:#e0e0e0;">⚡ System Status</span>
            <span class="badge badge-online">● Online</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.85em;">
            <div><span style="color:#a0a0b0;">Pipeline:</span> <span style="color:{state_color};font-weight:600;">{SYSTEM_STATUS['pipeline_state']}</span></div>
            <div><span style="color:#a0a0b0;">Transcripts:</span> <span style="color:#00d4ff;">{SYSTEM_STATUS['transcriptions']}</span></div>
            <div><span style="color:#a0a0b0;">VAD:</span> <span style="color:#00ff88;">{SYSTEM_STATUS['vad_status']}</span></div>
            <div><span style="color:#a0a0b0;">Wake Word:</span> <span style="color:#00ff88;">{SYSTEM_STATUS['wake_word']}</span></div>
            <div><span style="color:#a0a0b0;">LLM:</span> <span style="color:#00ff88;">{SYSTEM_STATUS['llm_status']}</span></div>
            <div><span style="color:#a0a0b0;">TTS:</span> <span style="color:#00ff88;">{SYSTEM_STATUS['tts_status']}</span></div>
        </div>
    </div>
    """


def build_model_card_html():
    """Build glass-styled model info card"""
    return f"""
    <div class="model-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <span class="model-card-title">🧠 Model Engine</span>
            <span class="badge badge-model">Whisper</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.85em;">
            <div><span style="color:#a0a0b0;">Model:</span> <span class="model-card-value">{SYSTEM_STATUS['whisper_model']}</span></div>
            <div><span style="color:#a0a0b0;">Device:</span> <span class="model-card-value">{SYSTEM_STATUS['device']}</span></div>
            <div><span style="color:#a0a0b0;">Language:</span> <span class="model-card-value">{SYSTEM_STATUS['language']}</span></div>
            <div><span style="color:#a0a0b0;">Port:</span> <span class="model-card-value">{SYSTEM_STATUS['api_port']}</span></div>
        </div>
    </div>
    """


# ──────────────────────────────────────────────
# GRADIO UI
# ──────────────────────────────────────────────
with gr.Blocks(
    title="ASR Voice Assistant",
) as app:

    # ── HEADER ──
    gr.HTML("""
    <div class="glass-panel" style="margin-bottom:16px;text-align:center;padding:12px;">
        <div class="title-text">🎤 Offline Voice Assistant</div>
        <div class="subtitle-text">ASR System v1.1.0 · Everything runs locally — no audio ever leaves your machine</div>
    </div>
    """)

    with gr.Row(equal_height=False):
        # ── LEFT SIDEBAR (Settings + Status + Model Card) ──
        with gr.Column(scale=1, min_width=260, elem_classes=["sidebar-panel"]):

            # Status panel
            status_display = gr.HTML(value=build_status_html())

            # Model card
            model_card = gr.HTML(value=build_model_card_html())

            # Model configuration
            gr.HTML("<div style='margin-top:12px;font-size:0.9em;color:#a0a0b0;font-weight:600;'>⚙️ Configuration</div>")
            with gr.Group():
                model_size = gr.Dropdown(
                    choices=["tiny", "base", "small", "medium", "large"],
                    value="small",
                    label="Whisper Model",
                    interactive=True,
                )
                device_select = gr.Dropdown(
                    choices=["cpu", "cuda"],
                    value="cpu",
                    label="Device",
                    interactive=True,
                )
                language_select = gr.Dropdown(
                    choices=["en", "hi", "es", "fr", "de", "ja", "zh", "auto"],
                    value="en",
                    label="Language",
                    interactive=True,
                )
                config_btn = gr.Button("Apply Config", variant="primary")

            # Wake word toggle
            gr.HTML("<div style='margin-top:16px;font-size:0.9em;color:#a0a0b0;font-weight:600;'>🎙️ Audio Pipeline</div>")
            with gr.Group():
                wake_toggle = gr.Checkbox(value=True, label="Wake Word Detection")
                vad_toggle = gr.Checkbox(value=True, label="VAD Endpointing")
                push_to_talk = gr.Checkbox(value=False, label="Push-to-Talk Mode (--no-wake)")

            # Audio file upload
            gr.HTML("<div style='margin-top:16px;font-size:0.9em;color:#a0a0b0;font-weight:600;'>📁 Upload Audio</div>")
            audio_upload = gr.File(
                label="Drop audio file",
                file_types=[".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"],
                type="filepath",
            )
            upload_btn = gr.Button("⚡ Transcribe File", variant="primary")

            # Clear conversation
            gr.HTML("<div style='margin-top:16px;'></div>")
            clear_btn = gr.Button("🗑️ Clear Chat", variant="stop")

        # ── MAIN AREA (Mic + Transcript + Waveform) ──
        with gr.Column(scale=3, min_width=500, elem_classes=["glass-panel"]):

            # Mic button area
            with gr.Row():
                with gr.Column(scale=1, min_width=100):
                    mic_status = gr.Textbox(
                        value="🎤 Tap to Record",
                        label="Mic Status",
                        interactive=False,
                        show_label=False,
                    )
                with gr.Column(scale=4):
                    mic_btn = gr.Button(
                        "🎙️",
                        variant="primary",
                        elem_classes=["mic-button"],
                    )
                with gr.Column(scale=2):
                    duration_display = gr.Textbox(
                        value="—",
                        label="Duration",
                        interactive=False,
                        show_label=True,
                    )

            # Waveform visualization
            waveform_plot = gr.LinePlot(
                value=None,
                x="time",
                y="amplitude",
                title="🔴 Live Audio Waveform",
                visible=False,
                elem_classes=["waveform-panel"],
            )

            # Chat / Transcript area
            chat_display = gr.HTML(value=build_chat_html())

            # Text input area
            with gr.Row():
                text_input = gr.Textbox(
                    placeholder="Type a message or command...",
                    label="Text Input",
                    show_label=False,
                    lines=1,
                    interactive=True,
                )
                send_btn = gr.Button("➤ Send", variant="primary")

            # Raw transcript + response (expandable)
            with gr.Accordion("📝 Raw Transcript & Response", open=False):
                raw_transcript = gr.Textbox(
                    value="",
                    label="Transcript",
                    interactive=False,
                    lines=2,
                )
                raw_response = gr.Textbox(
                    value="",
                    label="Response",
                    interactive=False,
                    lines=3,
                )

    # ── FOOTER ──
    gr.HTML("""
    <div class="footer-glass">
        <span>🔒 Offline-First · 🔊 Whisper ASR · 🧠 Ollama LLM · 🔉 pyttsx3/Piper TTS · v1.1.0</span>
    </div>
    """)

    # ──────────────────────────────────────────
    # EVENT HANDLERS
    # ──────────────────────────────────────────

    # Mic record toggle
    mic_btn.click(
        fn=start_recording,
        outputs=[mic_status, status_display, waveform_plot],
    ).then(
        fn=lambda: gr.update(value=generate_waveform_data(3), visible=True, title="🔴 Live Audio Waveform"),
        outputs=[waveform_plot],
    ).then(
        fn=stop_recording,
        outputs=[mic_status, chat_display, status_display, raw_transcript, raw_response, waveform_plot, duration_display],
    )

    # Text message send
    send_btn.click(
        fn=send_text_message,
        inputs=[text_input],
        outputs=[chat_display, status_display, text_input, raw_response],
    )

    # Also send on Enter key
    text_input.submit(
        fn=send_text_message,
        inputs=[text_input],
        outputs=[chat_display, status_display, text_input, raw_response],
    )

    # Audio file upload
    upload_btn.click(
        fn=upload_audio_file,
        inputs=[audio_upload],
        outputs=[chat_display, status_display, raw_transcript, raw_response],
    )

    # Config update
    config_btn.click(
        fn=update_model_config,
        inputs=[model_size, device_select, language_select],
        outputs=[status_display, model_card],
    )

    # Clear conversation
    clear_btn.click(
        fn=clear_conversation,
        outputs=[chat_display, status_display, raw_transcript, raw_response],
    )


# ──────────────────────────────────────────────
# LAUNCH — floating desktop window via pywebview
# ──────────────────────────────────────────────
def launch_desktop():
    """Launch as a native desktop floating window using pywebview"""
    import webview

    # Start Gradio in background
    server_thread = threading.Thread(
        target=lambda: app.launch(
            server_name="localhost",
            server_port=7860,
            share=False,
            prevent_thread_lock=True,
            inbrowser=False,
            theme=gr.themes.Default(
                primary_hue=gr.themes.colors.cyan,
                secondary_hue=gr.themes.colors.purple,
                neutral_hue=gr.themes.colors.gray,
            ),
            css=GLASS_CSS,
        ),
        daemon=True,
    )
    server_thread.start()
    time.sleep(2)  # Wait for server to start

    # Open in pywebview floating window
    window = webview.create_window(
        title="🎤 ASR Voice Assistant",
        url="http://localhost:7860",
        width=960,
        height=780,
        resizable=True,
        min_size=(700, 600),
        frameless=False,
        easy_drag=True,
    )
    webview.start()


def launch_browser():
    """Launch in browser (standard Gradio)"""
    app.launch(
        server_name="localhost",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Default(
            primary_hue=gr.themes.colors.cyan,
            secondary_hue=gr.themes.colors.purple,
            neutral_hue=gr.themes.colors.gray,
        ),
        css=GLASS_CSS,
    )


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "browser"

    if mode == "desktop":
        print("🖥️  Launching as desktop floating window...")
        launch_desktop()
    else:
        print("🌐  Launching in browser at http://localhost:7860...")
        launch_browser()
