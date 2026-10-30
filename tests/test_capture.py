"""Logic tests for capture.py that need no microphone and no PortAudio:
sounddevice is stubbed before import, so these run anywhere (CI included)."""
import os
import sys
import types
import unittest

import numpy as np

# Add project root to sys.path so 'src' is importable
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

# stub the audio driver BEFORE importing the module under test
# pyrefly: ignore [no-matching-overload]
sys.modules.setdefault("sounddevice", types.SimpleNamespace(
    PortAudioError=Exception, query_devices=lambda *a, **k: [],
    check_input_settings=lambda **k: None,
    _terminate=lambda: None, _initialize=lambda: None,
))

# pyrefly: ignore [missing-import]
from src.audio.capture import PrerollRing, Rebuffer, TARGET_RATE  # noqa: E402


class TestRebuffer(unittest.TestCase):
    def test_variable_chunks_become_exact_frames(self):
        rb = Rebuffer(1280)
        sizes = [480, 480, 480, 2000, 100, 1500]           # what blocksize=0 delivers
        frames = [f for s in sizes for f in rb.push(np.arange(s, dtype=np.int16))]
        self.assertTrue(all(len(f) == 1280 for f in frames))
        self.assertEqual(len(frames), sum(sizes) // 1280)  # nothing lost, nothing invented
        self.assertEqual(len(rb._buf), sum(sizes) % 1280)  # remainder retained

    def test_no_sample_reordering(self):
        rb = Rebuffer(4)
        out = np.concatenate(
            [f for c in (np.arange(0, 6), np.arange(6, 12)) for f in
             rb.push(c.astype(np.int16))])
        np.testing.assert_array_equal(out, np.arange(12, dtype=np.int16))

    def test_two_consumers_are_independent(self):
        wake, vad = Rebuffer(1280), Rebuffer(512)
        chunk = np.zeros(1300, dtype=np.int16)
        self.assertEqual(len(list(wake.push(chunk))), 1)
        self.assertEqual(len(list(vad.push(chunk))), 2)


class TestPrerollRing(unittest.TestCase):
    def test_caps_at_window_and_keeps_newest(self):
        ring = PrerollRing(ms=1000)                        # 16000 samples max
        for i in range(50):                                # push 3.2 s total
            ring.push(np.full(1024, i, dtype=np.int16))
        snap = ring.snapshot()
        self.assertEqual(len(snap), TARGET_RATE)           # exactly 1 s
        self.assertEqual(snap[-1], 49)                     # newest audio present
        self.assertGreaterEqual(snap[0], 33)               # oldest audio evicted

    def test_empty_ring(self):
        self.assertEqual(len(PrerollRing(ms=1000).snapshot()), 0)


if __name__ == "__main__":
    unittest.main()