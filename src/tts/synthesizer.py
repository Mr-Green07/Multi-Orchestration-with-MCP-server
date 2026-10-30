"""Offline TTS synthesizer using pyttsx3 (Windows SAPI5 / eSpeak).

Produces a float32 mono numpy array at the engine's native sample rate,
ready to hand directly to Playback.enqueue().

Usage:
    synth = TTSSynthesizer(cfg)
    audio = synth.synthesize("Hello, how can I help?")
    playback.enqueue(audio)
    playback.end_of_utterance()
"""
from __future__ import annotations

import logging
import os
import tempfile

# pyrefly: ignore [missing-import]
import numpy as np

log = logging.getLogger(__name__)


class TTSSynthesizer:
    """Text-to-speech using pyttsx3 (fully offline, zero extra models)."""

    def __init__(self, cfg: dict) -> None:
        tts_cfg = cfg.get("tts", {})
        self.sample_rate: int = tts_cfg.get("sample_rate", 22050)
        rate: int = tts_cfg.get("rate", 175)       # words-per-minute
        volume: float = float(tts_cfg.get("volume", 0.9))
        voice_id: str | None = tts_cfg.get("voice_id")  # None = system default

        try:
            # pyrefly: ignore [missing-import]
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", rate)
            self._engine.setProperty("volume", volume)
            if voice_id:
                self._engine.setProperty("voice", voice_id)
            log.info("TTS engine initialised (pyttsx3)")
        except ImportError as e:
            raise RuntimeError(
                "pyttsx3 is required for TTS. Install it with: uv add pyttsx3"
            ) from e

    # ------------------------------------------------------------------
    def synthesize(self, text: str) -> np.ndarray:
        """Convert *text* to a float32 mono PCM array (values in [-1, 1]).

        The engine saves a temp WAV, we read it back as float32, then delete.
        Using a temp file is the only pyttsx3 API that doesn't require a
        running event loop.
        """
        if not text or not text.strip():
            return np.zeros(0, dtype=np.float32)

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)
        try:
            self._engine.save_to_file(text, tmp_path)
            self._engine.runAndWait()
            return self._load_wav(tmp_path)
        except Exception as exc:
            log.error("TTS synthesis failed: %s", exc)
            return np.zeros(0, dtype=np.float32)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    @staticmethod
    def _load_wav(path: str) -> np.ndarray:
        """Read WAV file → float32 mono array normalised to [-1, 1]."""
        # pyrefly: ignore [missing-import]
        import scipy.io.wavfile as wavfile

        sr, audio = wavfile.read(path)
        # Normalise to float32 [-1, 1]
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2 ** 31
        elif audio.dtype == np.uint8:
            audio = (audio.astype(np.float32) - 128.0) / 128.0
        else:
            audio = audio.astype(np.float32)

        # Stereo → mono
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        return audio
