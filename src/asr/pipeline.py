# Audio pipeline: Mic → Wake → VAD → Brain → Playback.

# This is the always-on loop that ties every component together:

#   ┌─────────┐    ┌──────────┐    ┌─────┐    ┌───────┐    ┌──────────┐
#   │MicCapture├──►│ Rebuffer  ├──►│Wake │    │  VAD  │    │  Brain   │
#   │ (16 kHz) │    │1280 / 512│    │Word │    │Endptr │    │STT→NLU→… │
#   └─────────┘    └──────────┘    └──┬──┘    └──┬────┘    └────┬─────┘
#                                     │          │              │
#                               WAKE event   ENDPOINT      TTS audio
#                                     │      (utterance)        │
#                                     ▼          ▼              ▼
#                               ┌──────────────────────────────────┐
#                               │         Event Bus / FSM          │
#                               └──────────────────────────────────┘


from __future__ import annotations

import logging
import os
import sys
from typing import Callable
import threading
# pyrefly: ignore [missing-import]
import numpy as np

# Ensure project root is in sys.path when script is executed directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# pyrefly: ignore [missing-import]
from src.audio.capture import MicCapture, Rebuffer
# pyrefly: ignore [missing-import]
from src.audio.wakeword import WakeWordEngine
# pyrefly: ignore [missing-import]
from src.audio.vad import VadEndpointer
# pyrefly: ignore [missing-import]
from src.audio.output_handler import Playback
# pyrefly: ignore [missing-import]
from src.core.state import StateMachine, State
# pyrefly: ignore [missing-import]
from src.core.events import EventBus, Event
# pyrefly: ignore [missing-import]
from src.core.constants import AUDIO_SAMPLE_RATE_TTS
log = logging.getLogger(__name__)


class Pipeline:

    def __init__(
        self,
        cfg: dict,
        on_utterance: Callable[[np.ndarray, "Pipeline"], None],
        enable_wake_word: bool = True,
    ) -> None:
        self.cfg = cfg
        self._on_utterance = on_utterance
        self._enable_wake = enable_wake_word

        # --- components ---
                # --- Config & Fallbacks ---
        tts_rate = cfg.get("tts", {}).get("sample_rate", AUDIO_SAMPLE_RATE_TTS)

        # --- Components ---
        self.capture = MicCapture(cfg)
        self.wakeword = WakeWordEngine(cfg) if enable_wake_word else None
        self.vad = VadEndpointer(cfg)
        self.playback = Playback(cfg, samplerate=tts_rate)

        # --- Rebuffers ---
        self._wake_rb = Rebuffer(WakeWordEngine.FRAME_LEN)   # 1280 samples
        self._vad_rb = Rebuffer(VadEndpointer.FRAME_LEN)     # 512 samples

        # --- State Machine & Event Bus ---
        self.fsm = StateMachine()
        self.fsm.on_change = lambda old_s, new_s: log.debug(
            "State Shift: %s -> %s", old_s.name, new_s.name
        )
        self._bus = EventBus()

        # --- Control ---
        self._stop = threading.Event()
        self._audio_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
   
 

    
    def start(self) -> None:
        """Start the pipeline (blocks the calling thread)."""
        log.info("Pipeline starting…")

        # Audio producer thread: mic → wake/vad → events
        self._audio_thread = threading.Thread(
            target=self._audio_loop, name="audio-loop", daemon=True
        )
        self._audio_thread.start()

        # Main consumer loop runs on the calling thread
        try:
            self._main_loop()
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt — shutting down pipeline")
        finally:
            self.stop()

    def stop(self) -> None:
        """Graceful shutdown."""
        self._stop.set()
        self.capture.stop()
        self.playback.close()
        if self._audio_thread and self._audio_thread.is_alive():
            self._audio_thread.join(timeout=3.0)
        log.info("Pipeline stopped")

    # ------------------------------------------------------------------
    # Audio thread: mic → rebuffer → wake / VAD → publish events
    # ------------------------------------------------------------------
    def _audio_loop(self) -> None:
        """Runs on a daemon thread; produces events for the main loop."""
        log.info("Audio loop started (wake=%s)", "ON" if self._enable_wake else "OFF")

        # If wake word is disabled, go straight to LISTENING
        if not self._enable_wake:
            self._bus.publish(Event("wake"))

        listening = False  # local flag: are we forwarding frames to VAD?

        for chunk in self.capture.chunks():
            if self._stop.is_set():
                break

            # --- Wake-word detection (always feed, even during LISTENING) ---
            if self.wakeword is not None:
                for frame in self._wake_rb.push(chunk):
                    if self.wakeword.process(frame):
                        # Barge-in: if speaking, hard-stop playback
                        if self.fsm.state == State.SPEAKING:
                            self.playback.stop()
                            self._bus.publish(Event("barge_in"))
                        elif self.fsm.state == State.IDLE:
                            self._bus.publish(Event("wake"))

            # --- VAD processing (only while LISTENING) ---
            if self.fsm.state == State.LISTENING:
                if not listening:
                    # Just entered LISTENING: seed VAD with preroll
                    self.vad.reset()
                    preroll = self.capture.preroll.snapshot()
                    if len(preroll) > 0:
                        for frame in self._vad_rb.push(preroll):
                            evt = self.vad.process(frame)
                            if evt is not None and evt.kind == "endpoint":
                                self._bus.publish(
                                    Event("endpoint", payload=evt.audio)
                                )
                    listening = True

                for frame in self._vad_rb.push(chunk):
                    vad_evt = self.vad.process(frame)
                    if vad_evt is None:
                        continue
                    if vad_evt.kind == "speech_start":
                        self._bus.publish(Event("speech_start"))
                    elif vad_evt.kind == "endpoint":
                        self._bus.publish(
                            Event("endpoint", payload=vad_evt.audio)
                        )
                        listening = False
                    elif vad_evt.kind == "timeout":
                        self._bus.publish(Event("timeout"))
                        listening = False
            else:
                listening = False

        log.info("Audio loop exited")

    # ------------------------------------------------------------------
    # Main thread: consume events, drive FSM, call brain
    # ------------------------------------------------------------------
    def _main_loop(self) -> None:
        """Blocks forever, processing events from the audio thread."""
        log.info("Main loop started — waiting for events")
        while not self._stop.is_set():
            event = self._bus.next(timeout=0.5)
            if event is None:
                continue

            log.info("event: %s (state=%s)", event.kind, self.fsm.state.name)

            # ---- WAKE ----
            if event.kind == "wake":
                if self.fsm.state == State.IDLE:
                    self.fsm.transition(State.LISTENING)
                    self.playback.chime()
                    log.info("🔔 Wake word detected — listening…")

            # ---- BARGE-IN ----
            elif event.kind == "barge_in":
                if self.fsm.state == State.SPEAKING:
                    self.wakeword and self.wakeword.set_speaking(False)
                    self.fsm.transition(State.LISTENING)
                    log.info("🔇 Barge-in — switching to LISTENING")

            # ---- SPEECH START ----
            elif event.kind == "speech_start":
                log.debug("speech detected (VAD)")

            # ---- ENDPOINT (utterance captured) ----
            elif event.kind == "endpoint":
                if self.fsm.state == State.LISTENING:
                    self.fsm.transition(State.THINKING)
                    utterance: np.ndarray = event.payload
                    log.info(
                        "🎙️ Utterance captured: %.2f s (%d samples)",
                        len(utterance) / 16000,
                        len(utterance),
                    )

                    # Brain processes: STT → NLU → Task → LLM → TTS → Playback
                    try:
                        self.fsm.transition(State.SPEAKING)
                        if self.wakeword:
                            self.wakeword.set_speaking(True)
                        self._on_utterance(utterance, self)
                    except Exception as exc:
                        log.error("Brain processing failed: %s", exc, exc_info=True)

                    # Wait for playback to finish, then go IDLE
                    self.playback.wait_done(timeout=30.0)
                    if self.wakeword:
                        self.wakeword.set_speaking(False)

                    if self.fsm.state == State.SPEAKING:
                        self.fsm.transition(State.IDLE)
                        log.info("💤 Reply done — back to IDLE")

                    # If wake word is disabled, immediately re-enter LISTENING
                    if not self._enable_wake and self.fsm.state == State.IDLE:
                        self.fsm.transition(State.LISTENING)

            # ---- TIMEOUT (no speech after wake) ----
            elif event.kind == "timeout":
                if self.fsm.state == State.LISTENING:
                    self.fsm.transition(State.IDLE)
                    log.info("⏰ No speech detected — back to IDLE")

                    # If wake word is disabled, immediately re-enter LISTENING
                    if not self._enable_wake:
                        self.fsm.transition(State.LISTENING)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # pyrefly: ignore [missing-import]
    from src.core.brain import Brain
    # pyrefly: ignore [missing-import]
    from src.utils.helpers import safe_read_yaml
    # pyrefly: ignore [missing-import]
    from src.core.constants import ROOT_DIR

    config_path = ROOT_DIR / "config.yaml"
    cfg = safe_read_yaml(config_path) if config_path.exists() else {}
    
    brain = Brain(cfg)
    pipeline = Pipeline(cfg, on_utterance=brain.on_utterance, enable_wake_word=True)
    pipeline.start()

