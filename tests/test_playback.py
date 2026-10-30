"""Playback logic tests: sounddevice is stubbed; we drive the audio callback
by hand, which makes every timing behaviour deterministic."""
import unittest
import os
import sys
import numpy as np
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
try:
    # pyrefly: ignore [missing-import]
    from tests.sd_stub import sd_stub
except ImportError:      # discovered with start-dir tests/
    # pyrefly: ignore [missing-import]
    import sd_stub
sd_stub.install()

# pyrefly: ignore [missing-import]
from src.audio.output_handler import Playback  # noqa: E402


def make():
    return Playback({"audio": {}}, samplerate=22050)


def drain(pb, frames):
    out = np.zeros((frames, 1), dtype=np.int16)
    pb._callback(out, frames, None, None)
    return out[:, 0].copy()


class TestPlayback(unittest.TestCase):
    def test_samples_play_in_order_across_callback_boundaries(self):
        pb = make()
        pb.enqueue(np.arange(1000, dtype=np.int16))
        got = np.concatenate([drain(pb, 300) for _ in range(4)])
        np.testing.assert_array_equal(got[:1000], np.arange(1000))
        np.testing.assert_array_equal(got[1000:], 0)   # silence after

    def test_gap_between_sentences_is_not_done(self):
        pb = make()
        pb.enqueue(np.ones(500, dtype=np.int16))
        drain(pb, 600)                                  # sentence 1 drained
        self.assertTrue(pb.playing)                     # TTS still working
        pb.enqueue(np.ones(500, dtype=np.int16) * 2)    # sentence 2 arrives
        pb.end_of_utterance()
        drain(pb, 600)
        self.assertFalse(pb.playing)                    # NOW we're done
        self.assertTrue(pb.wait_done(0))

    def test_end_marker_on_already_drained_queue_sets_done(self):
        pb = make()
        pb.enqueue(np.ones(100, dtype=np.int16))
        drain(pb, 200)
        pb.end_of_utterance()                           # marker arrives late
        self.assertTrue(pb.wait_done(0))

    def test_stop_flushes_instantly(self):
        pb = make()
        pb.enqueue(np.ones(10_000, dtype=np.int16))
        drain(pb, 100)                                  # started playing
        pb.stop()                                       # barge-in!
        self.assertTrue(pb.wait_done(0))                # done immediately
        np.testing.assert_array_equal(drain(pb, 500), 0)  # only silence left

    def test_float_chunks_converted(self):
        pb = make()
        pb.enqueue(np.full(100, 0.5, dtype=np.float32))
        got = drain(pb, 100)
        self.assertTrue(np.all(np.abs(got.astype(np.int32) - 16383) <= 1))

    def test_chime_plays_and_completes(self):
        pb = make()
        pb.chime()
        self.assertTrue(pb.playing)
        total = np.concatenate([drain(pb, 1024) for _ in range(4)])
        self.assertGreater(np.abs(total.astype(np.int32)).max(), 1000)
        self.assertFalse(pb.playing)

    def test_passthrough_rate_when_device_accepts(self):
        pb = make()
        self.assertEqual(pb._out_rate, 22050)           # no resampler engaged


if __name__ == "__main__":
    unittest.main()
