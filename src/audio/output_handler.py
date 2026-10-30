"""Speaker output with instant kill for barge-in.

Consumes int16 mono PCM chunks (from TTS, at the voice's native rate --
Piper: 22050 Hz) and plays them through a persistent sounddevice
OutputStream. Design decisions encoded here:

  callback, not write() : a blocked stream.write() cannot be interrupted
                          cleanly; with a callback, stop() just clears the
                          pending buffer and the next callback emits silence.
                          Kill latency ~= one blocksize.
  persistent stream     : opened once, never closed between replies.
                          Open/close per utterance costs 50-200 ms and can
                          click; playing silence while idle costs nothing.
  silence-fill on empty : an empty buffer usually means "TTS is still
                          synthesizing the next sentence", NOT "reply done".
                          The stream keeps rolling and fills silence.
  end_of_utterance()    : the ONLY way "done" can be decided. The done event
                          fires when (ended AND buffer drained) -- that is
                          the FSM's SPEAKING -> IDLE trigger.
  rate negotiation      : ask the device for the voice's rate; if refused,
                          resample (polyphase) to the device default --
                          mirror of capture.py, opposite direction.

Barge-in wiring (pipeline): wake fires during SPEAKING -> playback.stop()
-> wakeword.set_speaking(False) -> state LISTENING. stop() is hard-cut on
purpose; the user is already talking over us.

Self-test:  python -m app.audio.playback   (plays the chime + a test tone)
"""
from __future__ import annotations

import logging
import threading
from collections import deque

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class Playback:
    def __init__(self, cfg: dict, samplerate: int = 22050) -> None:
        a = cfg.get("audio", {})
        self.src_rate = samplerate                  # what TTS produces
        self.device = self._find_output(a.get("output_device_name"))
        self._chunks: deque = deque()
        self._pos = 0                               # offset into chunks[0]
        self._ended = True                          # no utterance in flight
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._done.set()
        self._stream = None
        self._out_rate, self._resample = self._negotiate_rate()

    # -- device / rate negotiation ---------------------------------------
    @staticmethod
    def _find_output(name_part: str | None) -> int | None:
        if not name_part:
            return None
        for i, d in enumerate(sd.query_devices()):
            if (name_part.lower() in d["name"].lower()
                    and d["max_output_channels"] > 0):
                return i
        raise LookupError(f"no output device matching {name_part!r}")

    def _negotiate_rate(self):
        try:
            sd.check_output_settings(device=self.device,
                                     samplerate=self.src_rate,
                                     channels=1, dtype="int16")
            return self.src_rate, (lambda x: x)
        except sd.PortAudioError:
            info = sd.query_devices(self.device, kind="output")
            out = int(info["default_samplerate"])
            log.warning("output refuses %d Hz; resampling to %d",
                        self.src_rate, out)
            from math import gcd
            from scipy.signal import resample_poly   # lazy: fallback only

            g = gcd(out, self.src_rate)
            up, down = out // g, self.src_rate // g

            def rs(x: np.ndarray) -> np.ndarray:
                y = resample_poly(x.astype(np.float32), up, down)
                return np.clip(y, -32768, 32767).astype(np.int16)

            return out, rs

    # -- producer API (TTS thread) ----------------------------------------
    def enqueue(self, pcm: np.ndarray) -> None:
        pcm = np.asarray(pcm)
        if pcm.dtype.kind == "f":                   # float [-1,1] -> int16
            pcm = (pcm * 32767.0).clip(-32768, 32767).astype(np.int16)
        elif pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)
        pcm = self._resample(pcm)
        with self._lock:
            self._chunks.append(pcm)
            self._ended = False
            self._done.clear()
        self._ensure_stream()

    def end_of_utterance(self) -> None:
        """TTS promises no more chunks for this reply."""
        with self._lock:
            self._ended = True
            if not self._chunks:                    # already drained
                self._done.set()

    def chime(self) -> None:
        """Two-tone wake acknowledgment -- synthesized, no asset file."""
        sr = self.src_rate
        t = np.arange(int(0.12 * sr)) / sr
        env = np.minimum(1.0, np.minimum(t / 0.01, (t[-1] - t) / 0.03))
        tone = (0.18 * np.sin(2 * np.pi * 880 * t)
                + 0.12 * np.sin(2 * np.pi * 1320 * t)) * env
        self.enqueue(tone)
        self.end_of_utterance()

    # -- control (FSM) ------------------------------------------------------
    def stop(self) -> None:
        """Barge-in: hard flush. Silence within ~one blocksize."""
        with self._lock:
            self._chunks.clear()
            self._pos = 0
            self._ended = True
        self._done.set()

    def wait_done(self, timeout: float | None = None) -> bool:
        """Block until the reply has fully played (FSM: SPEAKING -> IDLE)."""
        return self._done.wait(timeout)

    @property
    def playing(self) -> bool:
        return not self._done.is_set()

    def close(self) -> None:
        self.stop()
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    # -- audio callback (PortAudio C thread: fill, never block) -----------
    def _callback(self, outdata, frames, time_info, status) -> None:
        out = outdata[:, 0]
        filled = 0
        with self._lock:
            while filled < frames and self._chunks:
                chunk = self._chunks[0]
                n = min(frames - filled, len(chunk) - self._pos)
                out[filled:filled + n] = chunk[self._pos:self._pos + n]
                self._pos += n
                filled += n
                if self._pos >= len(chunk):
                    self._chunks.popleft()
                    self._pos = 0
            if filled < frames:
                out[filled:] = 0                    # silence-fill, keep rolling
                if self._ended and not self._chunks:
                    self._done.set()                # reply fully played

    def _ensure_stream(self) -> None:
        if self._stream is not None and getattr(self._stream, "active", True):
            return
        try:
            if self._stream is not None:
                self._stream.close()
            self._stream = sd.OutputStream(
                device=self.device, samplerate=self._out_rate, channels=1,
                dtype="int16", blocksize=0, latency="low",
                callback=self._callback)
            self._stream.start()
        except sd.PortAudioError as e:              # no speakers: drop reply,
            log.error("cannot open output device: %s", e)   # don't crash
            self.stop()


if __name__ == "__main__":  # audible self-test
    import time
    logging.basicConfig(level=logging.INFO)
    pb = Playback({"audio": {}}, samplerate=22050)
    print("chime...")
    pb.chime()
    pb.wait_done(3)
    time.sleep(0.3)
    print("1 s test tone (440 Hz)...")
    t = np.arange(22050) / 22050
    pb.enqueue(0.2 * np.sin(2 * np.pi * 440 * t))
    pb.end_of_utterance()
    pb.wait_done(3)
    pb.close()
    print("done -- if you heard ping + tone, playback works")