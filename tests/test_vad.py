"""Endpointer logic tests: the Silero model is injected as a scripted fake,
frame timing uses tiny windows so the suite runs in milliseconds."""
import unittest
import os
import sys
import numpy as np
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
# pyrefly: ignore [missing-import]
from src.audio.vad import FRAME_LEN, VadEndpointer


class FakeSilero:
    def __init__(self):
        self.probs, self.resets, self.inputs = [], 0, []

    def __call__(self, frame_f32):
        self.inputs.append(frame_f32)
        return self.probs.pop(0) if self.probs else 0.0

    def reset(self):
        self.resets += 1


def make(**over):
    v = {"speech_threshold": 0.5, "exit_threshold": 0.35, "start_frames": 2,
         "endpoint_silence_ms": 96,        # 3 frames
         "no_speech_timeout_s": 3.2,       # 100 frames -- out of the way
         "max_utterance_s": 0.64,          # 20 frames
         "pre_speech_pad_ms": 64}          # 2 frames
    v.update(over)
    fake = FakeSilero()
    return VadEndpointer({"vad": v}, model=fake), fake


def frame(tag: int) -> np.ndarray:
    return np.full(FRAME_LEN, tag, dtype=np.int16)


class TestEndpointer(unittest.TestCase):
    def test_speech_start_needs_consecutive_frames(self):
        ep, fake = make()
        fake.probs = [0.9, 0.2, 0.9, 0.9]           # spike, drop, then real
        events = [ep.process(frame(i)) for i in range(4)]
        self.assertEqual([e.kind if e else None for e in events],
                         [None, None, None, "speech_start"])

    def test_endpoint_collects_utterance_with_prepad(self):
        ep, fake = make()
        #        0    1    2    3    4    5    6    7    8
        fake.probs = [0.1, 0.1, 0.1, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1]
        result = [ep.process(frame(i)) for i in range(9)]
        end = result[-1]
        self.assertEqual(end.kind, "endpoint")
        self.assertEqual(end.reason, "silence")
        # pre_pad(maxlen=4) held frames 1..4 at speech_start; + frames 5..8
        self.assertEqual(len(end.audio), 8 * FRAME_LEN)
        self.assertEqual(end.audio[0], 1)            # pre-pad audio included
        self.assertEqual(end.audio[-1], 8)           # up to the last frame

    def test_hysteresis_mid_word_wobble_is_not_silence(self):
        ep, fake = make()
        fake.probs = [0.9, 0.9] + [0.4] * 10         # 0.4 < 0.5 but > 0.35
        events = [ep.process(frame(i)) for i in range(12)]
        self.assertTrue(all(e is None or e.kind == "speech_start"
                            for e in events))        # never endpoints

    def test_no_speech_timeout(self):
        ep, fake = make(no_speech_timeout_s=0.096)   # 3 frames, on purpose
        fake.probs = [0.1, 0.1, 0.1]
        events = [ep.process(frame(i)) for i in range(3)]
        self.assertEqual(events[-1].kind, "timeout")

    def test_max_utterance_forces_endpoint(self):
        ep, fake = make()
        fake.probs = [0.9] * 30                      # never stops talking
        events = [ep.process(frame(i)) for i in range(30)]
        ends = [e for e in events if e and e.kind == "endpoint"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0].reason, "max_length")
        self.assertEqual(len(ends[0].audio), 20 * FRAME_LEN)

    def test_auto_reset_allows_second_utterance(self):
        ep, fake = make()
        fake.probs = [0.9, 0.9, 0.1, 0.1, 0.1] * 2   # two utterances
        kinds = [e.kind for i in range(10)
                 if (e := ep.process(frame(i))) is not None]
        self.assertEqual(kinds, ["speech_start", "endpoint"] * 2)
        self.assertGreaterEqual(fake.resets, 3)      # init + each endpoint

    def test_model_receives_normalized_float32(self):
        ep, fake = make()
        ep.process(np.full(FRAME_LEN, 16384, dtype=np.int16))
        x = fake.inputs[0]
        self.assertEqual(x.dtype, np.float32)
        self.assertAlmostEqual(float(x[0]), 0.5, places=3)

    def test_wrong_frame_length_raises(self):
        ep, _ = make()
        with self.assertRaises(ValueError):
            ep.process(np.zeros(1280, dtype=np.int16))


if __name__ == "__main__":
    unittest.main()
