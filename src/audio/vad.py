"""VAD + endpointing (Silero VAD v5 via onnxruntime, CPU).

Silero answers one question per 512-sample (32 ms) frame: "how speech-like
was that?" (a probability). This module builds the ENDPOINTER on top -- the
state machine that turns a probability stream into utterances:

  WAITING --(prob >= speech_threshold for start_frames)--> IN_SPEECH
  WAITING --(no_speech_timeout with no speech)-----------> TIMEOUT event
  IN_SPEECH --(prob < exit_threshold for endpoint_ms)----> ENDPOINT event
  IN_SPEECH --(max_utterance_s reached)------------------> ENDPOINT (forced)

Design rules encoded here:
  hysteresis   : enter speech at speech_threshold (0.5), but only count
                 silence below exit_threshold (0.35). Probabilities flap
                 around 0.5 mid-word; the gap stops premature endpoints.
  audio clock  : silence/timeouts are counted in FRAMES, never wall time.
                 512 samples IS 32 ms of audio; wall clocks measure our CPU
                 hiccups, not the user's pause.
  pre-pad      : speech is confirmed a few frames after it starts, so the
                 utterance buffer is seeded with the frames just before
                 detection -- soft onsets ("seven") survive.
  auto-reset   : ENDPOINT/TIMEOUT reset everything (incl. the RNN state --
                 Silero is stateful and bleeds probabilities across
                 utterances otherwise). reset() is also called on every wake.

Wiring note (pipeline): on wake, push the tail of capture.preroll through
process() before live frames -- words spoken WHILE the wake word was being
confirmed then flow through the same path as everything else.

Future optimization (how big assistants feel instant): semantic endpointing
-- shorten endpoint_ms when the partial STT transcript already parses as a
complete command. Requires streaming STT; revisit after Milestone 2.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

FRAME_LEN = 512               # the ONLY chunk size Silero v5 accepts @ 16 kHz
FRAME_MS = FRAME_LEN / 16.0   # 32 ms of audio per frame


def _ms_to_frames(ms: float) -> int:
    return max(1, round(ms / FRAME_MS))


@dataclass
class VadEvent:
    kind: str                     # "speech_start" | "endpoint" | "timeout"
    audio: np.ndarray | None = None   # full utterance (int16) on endpoint
    reason: str = ""              # endpoint: "silence" | "max_length"


class SileroOnnx:
    """Minimal stateful wrapper around silero_vad.onnx (v5 graph)."""

    def __init__(self, path: str) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1      # 2 MB model; threads cost more
        opts.inter_op_num_threads = 1      # than they save at this size
        self._sess = ort.InferenceSession(
            path, sess_options=opts, providers=["CPUExecutionProvider"])

        names = {i.name for i in self._sess.get_inputs()}
        if not {"input", "state", "sr"} <= names:
            raise RuntimeError(
                f"expected Silero v5 graph (inputs input/state/sr), got "
                f"{sorted(names)} -- a v4 file uses h/c states; re-download "
                "via scripts/download_models.sh")
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def __call__(self, frame_f32: np.ndarray) -> float:
        # pyrefly: ignore [bad-assignment]
        out, self._state = self._sess.run(
            ["output", "stateN"],
            {"input": frame_f32[None, :],
             "state": self._state,
             "sr": np.array(16000, dtype=np.int64)})
        # pyrefly: ignore [bad-index]
        return float(out[0, 0])


class VadEndpointer:
    """Feed 512-sample int16 frames; get speech_start/endpoint/timeout events."""
    FRAME_LEN = FRAME_LEN  # expose as class attribute for pipeline wiring

    def __init__(self, cfg: dict, model=None) -> None:  # model injectable: tests
        v = cfg["vad"]
        self.speech_threshold = float(v.get("speech_threshold", 0.5))
        self.exit_threshold = float(v.get("exit_threshold", 0.35))
        self.start_frames = int(v.get("start_frames", 3))
        self.endpoint_frames = _ms_to_frames(v.get("endpoint_silence_ms", 600))
        self.timeout_frames = _ms_to_frames(
            1000.0 * v.get("no_speech_timeout_s", 6.0))
        self.max_frames = _ms_to_frames(1000.0 * v.get("max_utterance_s", 15))
        pad_frames = _ms_to_frames(v.get("pre_speech_pad_ms", 240))
        self._pre_pad: deque = deque(maxlen=pad_frames + self.start_frames)
        self.model = model if model is not None else SileroOnnx(
            v.get("model_path", "models/silero_vad.onnx"))
        self.last_prob = 0.0        # exposed for tuning / debug meter
        self.reset()

    def reset(self) -> None:
        """New listening session: clear RNN state, counters, and buffers."""
        self.model.reset()
        self._in_speech = False
        self._above = 0
        self._silence = 0
        self._frames_seen = 0
        self._buf: list[np.ndarray] = []
        self._pre_pad.clear()

    # ------------------------------------------------------------------
    def process(self, frame: np.ndarray) -> VadEvent | None:
        if len(frame) != FRAME_LEN:
            raise ValueError(
                f"VAD frames must be {FRAME_LEN} samples, got {len(frame)} "
                f"-- feed me through Rebuffer({FRAME_LEN})")
        if frame.dtype != np.int16:
            frame = np.asarray(frame)
            frame = ((frame * 32767.0).astype(np.int16)
                     if frame.dtype.kind == "f" else frame.astype(np.int16))

        # Silero wants float32 in [-1, 1]; we keep int16 for the buffers
        self.last_prob = self.model(frame.astype(np.float32) / 32768.0)
        self._frames_seen += 1

        if not self._in_speech:
            self._pre_pad.append(frame)
            self._above = self._above + 1 \
                if self.last_prob >= self.speech_threshold else 0
            if self._above >= self.start_frames:
                self._in_speech = True
                self._buf = list(self._pre_pad)     # onset survives (pre-pad)
                self._silence = 0
                return VadEvent("speech_start")
            if self._frames_seen >= self.timeout_frames:
                self.reset()
                return VadEvent("timeout")
            return None

        # -- in speech ---------------------------------------------------
        self._buf.append(frame)
        # hysteresis: only prob < exit_threshold counts toward the endpoint
        self._silence = self._silence + 1 \
            if self.last_prob < self.exit_threshold else 0

        if self._silence >= self.endpoint_frames:
            return self._finish("silence")
        if len(self._buf) >= self.max_frames:
            return self._finish("max_length")
        return None

    def _finish(self, reason: str) -> VadEvent:
        audio = np.concatenate(self._buf)
        self.reset()                                # auto-arm for next session
        log.info("endpoint (%s): %.2f s of audio", reason, len(audio) / 16000)
        return VadEvent("endpoint", audio=audio, reason=reason)