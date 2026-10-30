from __future__ import annotations

import collections
import logging
import queue
import threading
import time
from math import gcd
from typing import Callable, Iterator

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

TARGET_RATE = 16_000


class Rebuffer:
    """Accepts arbitrary-length sample arrays, yields fixed-length frames.

    Decouples the driver's delivery size (blocksize=0 -> variable) from each
    engine's required size. One instance per consumer, because each consumer
    keeps its own remainder.
    """

    def __init__(self, frame_len: int) -> None:
        self.frame_len = frame_len
        self._buf = np.empty(0, dtype=np.int16)

    def push(self, samples: np.ndarray) -> Iterator[np.ndarray]:
        self._buf = np.concatenate([self._buf, samples])
        while len(self._buf) >= self.frame_len:
            frame = self._buf[: self.frame_len]
            self._buf = self._buf[self.frame_len :]
            yield frame


class PrerollRing:
    """Rolling window of the last `ms` milliseconds of 16 kHz audio.

    snapshot() is called exactly once per wake to seed the STT stream, so the
    words spoken WHILE the wake word was still being confirmed aren't lost.
    Stores whole chunks (no per-sample shuffling); trims by popping old chunks.
    """

    def __init__(self, ms: int) -> None:
        self._max_samples = TARGET_RATE * ms // 1000
        self._chunks: collections.deque = collections.deque()
        self._samples = 0
        self._lock = threading.Lock()  # producer=consumer-thread, reader=main

    def push(self, chunk: np.ndarray) -> None:
        with self._lock:
            self._chunks.append(chunk)
            self._samples += len(chunk)
            # drop oldest chunks while we'd STILL hold >= max without them
            while self._chunks and (
                self._samples - len(self._chunks[0]) >= self._max_samples
            ):
                self._samples -= len(self._chunks.popleft())

    def snapshot(self) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.empty(0, dtype=np.int16)
            return np.concatenate(list(self._chunks))[-self._max_samples :]


def find_input_device(name_part: str | None) -> int | None:
    """#7 — resolve a device by name substring; None -> PortAudio default."""
    if not name_part:
        return None
    for idx, dev in enumerate(sd.query_devices()):
        if name_part.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            return idx
    raise LookupError(
        f"no input device matching {name_part!r} — run "
        "python -c 'import sounddevice; print(sounddevice.query_devices())'"
    )


class MicCapture:
    """Owns the InputStream; hands the pipeline a stream of 16 kHz chunks."""

    def __init__(self, cfg: dict) -> None:
        a = cfg["audio"]
        self.device = find_input_device(a.get("device_name"))
        self.preroll = PrerollRing(a.get("preroll_ms", 1000))
        self._q: "queue.Queue[np.ndarray]" = queue.Queue(
            maxsize=a.get("queue_max_chunks", 100)
        )
        self._running = threading.Event()
        self._dropped = 0          # overflow counter (callback can't log)
        self._status_flags = 0     # PortAudio over/underflow flags, ditto
        self._native_rate = self._probe_rate()
        self._to_16k = self._make_resampler(self._native_rate)

    # -- #6: sample-rate negotiation ------------------------------------
    def _probe_rate(self) -> int:
        try:
            sd.check_input_settings(
                device=self.device, samplerate=TARGET_RATE, channels=1, dtype="int16"
            )
            return TARGET_RATE
        except sd.PortAudioError:
            info = sd.query_devices(self.device, kind="input")
            native = int(info["default_samplerate"])
            log.warning("mic refuses 16 kHz; capturing at %d Hz + resampling", native)
            return native

    def _make_resampler(self, native: int) -> Callable[[np.ndarray], np.ndarray]:
        if native == TARGET_RATE:
            return lambda x: x
        # lazy import: scipy is only a dependency on the fallback path
        from scipy.signal import resample_poly

        g = gcd(TARGET_RATE, native)
        up, down = TARGET_RATE // g, native // g  # 48k->16k: 1/3, 44.1k: 160/441

        def _resample(x: np.ndarray) -> np.ndarray:
            y = resample_poly(x.astype(np.float32), up, down)  # anti-aliased
            return np.clip(y, -32768, 32767).astype(np.int16)

        return _resample

    # -- #3: the audio callback (PortAudio C thread — copy, enqueue, leave)
    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self._status_flags += 1
        chunk = indata[:, 0].copy()  # MANDATORY copy: PortAudio reuses indata
        try:
            self._q.put_nowait(chunk)
        except queue.Full:           # consumer stalled: drop OLDEST, keep newest
            try:
                self._q.get_nowait()
                self._q.put_nowait(chunk)
                self._dropped += 1
            except (queue.Empty, queue.Full):
                pass

    # -- consumer side ----------------------------------------------------
    def chunks(self) -> Iterator[np.ndarray]:
        """Yield 16 kHz int16 arrays of arbitrary length until stop().

        Owns the stream lifecycle, including the #8 watchdog: on device loss
        the stream is reopened every 2 s until the mic comes back.
        """
        self._running.set()
        while self._running.is_set():
            try:
                with sd.InputStream(
                    device=self.device,
                    samplerate=self._native_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=0,          # let PortAudio pick; Rebuffer absorbs it
                    callback=self._callback,
                ) as stream:
                    log.info(
                        "mic open: device=%s rate=%d", self.device, self._native_rate
                    )
                    while self._running.is_set():
                        try:
                            raw = self._q.get(timeout=0.5)
                        except queue.Empty:
                            if not stream.active:  # device vanished silently
                                raise sd.PortAudioError("stream went inactive")
                            continue               # timeout lets stop() land
                        if self._dropped:
                            log.warning("dropped %d chunks (consumer too slow)",
                                        self._dropped)
                            self._dropped = 0
                        chunk = self._to_16k(raw)
                        self.preroll.push(chunk)
                        yield chunk
            except sd.PortAudioError as e:
                if not self._running.is_set():
                    break
                log.warning("audio device lost (%s) — reopening in 2 s", e)
                sd._terminate()
                sd._initialize()  # force PortAudio to re-scan the device list
                time.sleep(2.0)

    def stop(self) -> None:
        self._running.clear()


if __name__ == "__main__":  # scenario #1: mic sanity check / live level meter
    logging.basicConfig(level=logging.INFO)
    cap = MicCapture({"audio": {"preroll_ms": 1000}})
    print("speak for ~5 s — bars should move; flat zero = wrong device/permission")
    t_end = time.monotonic() + 5
    for c in cap.chunks():
        peak = int(np.abs(c).max())
        print(f"\r|{'#' * (peak * 50 // 32768):<50}| {peak:5d}", end="", flush=True)
        if time.monotonic() > t_end:
            cap.stop()
    print(f"\npre-roll holds {len(cap.preroll.snapshot())} samples")