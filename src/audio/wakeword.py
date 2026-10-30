"""Always-on wake-word engine (openWakeWord wrapper).

How detection works, per 1280-sample (80 ms) frame:
  raw int16 audio -> streaming log-mel spectrogram -> shared speech-embedding
  backbone -> tiny per-phrase classifier head -> score in [0, 1]. The mel and
  embedding stages keep internal ring buffers, so the model is STATEFUL:
  feed it continuous, in-order audio, always.

Raw openWakeWord scores are not detections. This wrapper adds the production
behaviours the raw model lacks:

  debounce      : N consecutive frames >= threshold, not one lucky spike
  cooldown      : refractory period after a fire (scores stay high ~0.5 s and
                  would re-trigger every frame without it)
  state reset   : model.reset() on fire, so the TAIL of the wake phrase in
                  the internal buffers cannot fire it a second time
  barge-in mode : higher threshold while our own TTS is audible; the engine
                  is never paused (pausing would kill barge-in entirely)
  input guards  : int16 + exactly 1280 samples enforced (wrong dtype gives
                  silently-zero scores, not errors)

Framework: inference_framework="onnx" is forced -- the tflite default has no
wheels on modern Windows/Python, and we ship onnxruntime regardless.

Self-test:  python -m app.audio.wakeword   (live: say "hey jarvis")
"""
from __future__ import annotations

import logging
import time
from typing import Callable
import os
import sys
import numpy as np

log = logging.getLogger(__name__)


class WakeWordEngine:
    FRAME_LEN = 1280  # 80 ms @ 16 kHz -- what oWW's melspec pipeline is tuned for

    def __init__(self, cfg: dict,
                 now_fn: Callable[[], float] = time.monotonic) -> None:
        w = cfg["wakeword"]
        self.threshold = float(w.get("threshold", 0.6))
        self.speaking_threshold = float(w.get("speaking_threshold", 0.75))
        self.consecutive_frames = int(w.get("consecutive_frames", 2))
        self.cooldown_s = float(w.get("cooldown_s", 2.0))
        self._now = now_fn          # injectable clock -> logic is unit-testable
        self._above = 0             # consecutive frames currently >= threshold
        self._last_fire = float("-inf")
        self._speaking = False
        self.last_score = 0.0       # exposed for threshold tuning / level meter
        self.model = self._load(w.get("model", "models/alexa.onnx"))

    @staticmethod
    def _load(name_or_path: str):
        """Accepts a built-in name ('hey_jarvis') or a path to a custom .onnx."""
        import openwakeword
        from openwakeword.model import Model

        kwargs = dict(wakeword_models=[name_or_path], inference_framework="onnx")
        try:
            return Model(**kwargs)
        except Exception:
            # first-run bootstrap: melspec/embedding/phrase models not on disk.
            # download_models.sh prefetches these; this is the belt to that
            # suspenders. After this, the assistant is fully offline.
            log.info("openWakeWord models missing -- downloading once")
            openwakeword.utils.download_models()
            return Model(**kwargs)

    # -- pipeline API -----------------------------------------------------
    def process(self, frame: np.ndarray) -> bool:
        """Feed ONE 1280-sample frame; returns True once per wake utterance."""
        if len(frame) != self.FRAME_LEN:
            raise ValueError(
                f"wake frames must be {self.FRAME_LEN} samples, got "
                f"{len(frame)} -- feed me through Rebuffer({self.FRAME_LEN})")
        if frame.dtype != np.int16:
            # float audio in [-1, 1] would score ~0 forever with no error
            if frame.dtype.kind == "f":
                frame = (np.asarray(frame) * 32767.0).astype(np.int16)
            else:
                frame = frame.astype(np.int16)

        # ALWAYS predict, even inside cooldown: the model is stateful and
        # needs continuous audio. We gate the trigger, never the feed.
        # max() over values: the dict key is the model's INTERNAL name
        # ("hey_jarvis_v0.1"), never index it by the config string.
        self.last_score = float(max(self.model.predict(frame).values()))

        if self._now() - self._last_fire < self.cooldown_s:
            self._above = 0
            return False

        thr = self.speaking_threshold if self._speaking else self.threshold
        self._above = self._above + 1 if self.last_score >= thr else 0

        if self._above >= self.consecutive_frames:
            self._above = 0
            self._last_fire = self._now()
            self.model.reset()   # clear mel/embedding buffers: no tail re-fire
            log.info("wake fired (score=%.2f thr=%.2f)", self.last_score, thr)
            return True
        return False

    def set_speaking(self, speaking: bool) -> None:
        """Barge-in mode: raise the bar while our own TTS is audible."""
        self._speaking = speaking

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))
if __name__ == "__main__":  # live test: capture -> rebuffer -> wake engine
    logging.basicConfig(level=logging.INFO)
    # pyrefly: ignore [missing-import]
    from src.audio.capture import MicCapture, Rebuffer

    # Load config from project root
    cfg = {"audio": {"preroll_ms": 1000},
           "wakeword": {"model": "hey_jarvis", "threshold": 0.6,
                        "consecutive_frames": 2, "cooldown_s": 2.0}}
   
    engine = WakeWordEngine(cfg)
    cap = MicCapture(cfg)
    rb = Rebuffer(WakeWordEngine.FRAME_LEN)
    print("listening -- say 'hey jarvis' (Ctrl-C to quit)")
    try:
        for chunk in cap.chunks():
            for frame in rb.push(chunk):
                fired = engine.process(frame)
                bar = "#" * int(engine.last_score * 40)
                print(f"\r[{bar:<40}] {engine.last_score:.2f}", end="", flush=True)
                if fired:
                    pre = cap.preroll.snapshot()
                    print(f"\n*** WAKE ***  (pre-roll ready: {len(pre)} samples)")
    except KeyboardInterrupt:
        cap.stop()