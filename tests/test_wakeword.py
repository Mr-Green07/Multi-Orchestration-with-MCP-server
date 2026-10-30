"""Detection-logic tests: openwakeword is stubbed, the clock is injected,
so every timing behaviour is testable in milliseconds with no mic."""
import sys
import types
import unittest
import os
import sys
import numpy as np
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np


class FakeModel:
    """Scripted score stream + call recorder."""
    def __init__(self, **kwargs):
        self.scores, self.resets, self.frames = [], 0, []

    def predict(self, frame):
        self.frames.append(frame)
        s = self.scores.pop(0) if self.scores else 0.0
        return {"hey_jarvis_v0.1": s}   # internal name != config name (bug #5)

    def reset(self):
        self.resets += 1


_model_mod = types.ModuleType("openwakeword.model")
# pyrefly: ignore [missing-attribute]
_model_mod.Model = FakeModel
_oww = types.ModuleType("openwakeword")
# pyrefly: ignore [missing-attribute]
_oww.model = _model_mod
# pyrefly: ignore [missing-attribute]
_oww.utils = types.SimpleNamespace(download_models=lambda *a, **k: None)
sys.modules["openwakeword"] = _oww
sys.modules["openwakeword.model"] = _model_mod

# pyrefly: ignore [missing-import]
from src.audio.wakeword import WakeWordEngine  # noqa: E402

FRAME = np.zeros(1280, dtype=np.int16)


def make_engine(**over):
    w = {"model": "hey_jarvis", "threshold": 0.6, "consecutive_frames": 2,
         "cooldown_s": 2.0, "speaking_threshold": 0.75}
    w.update(over)
    clock = {"t": 0.0}
    eng = WakeWordEngine({"wakeword": w}, now_fn=lambda: clock["t"])
    return eng, clock


class TestDetectionLogic(unittest.TestCase):
    def test_debounce_needs_consecutive_frames(self):
        eng, _ = make_engine()
        eng.model.scores = [0.9, 0.9]
        self.assertEqual([eng.process(FRAME) for _ in range(2)], [False, True])

    def test_isolated_spikes_never_fire(self):
        eng, _ = make_engine()
        eng.model.scores = [0.9, 0.3, 0.9, 0.3, 0.9, 0.3]
        self.assertTrue(not any(eng.process(FRAME) for _ in range(6)))

    def test_cooldown_blocks_refire_but_keeps_feeding_model(self):
        eng, clock = make_engine()
        eng.model.scores = [0.9] * 10
        fires = [eng.process(FRAME) for _ in range(10)]
        self.assertEqual(sum(fires), 1)                  # one utterance, one wake
        self.assertEqual(len(eng.model.frames), 10)      # feed never gated
        clock["t"] = 2.5                                 # past cooldown
        eng.model.scores = [0.9, 0.9]
        self.assertEqual([eng.process(FRAME) for _ in range(2)], [False, True])

    def test_reset_called_exactly_once_per_fire(self):
        eng, _ = make_engine()
        eng.model.scores = [0.9] * 6
        [eng.process(FRAME) for _ in range(6)]
        self.assertEqual(eng.model.resets, 1)

    def test_speaking_mode_raises_threshold(self):
        eng, _ = make_engine()
        eng.set_speaking(True)
        eng.model.scores = [0.65, 0.65]                  # beats 0.6, not 0.75
        self.assertTrue(not any(eng.process(FRAME) for _ in range(2)))
        eng.model.scores = [0.8, 0.8]                    # a real shout wins
        self.assertEqual([eng.process(FRAME) for _ in range(2)], [False, True])

    def test_wrong_frame_length_raises(self):
        eng, _ = make_engine()
        with self.assertRaises(ValueError):
            eng.process(np.zeros(512, dtype=np.int16))

    def test_float_audio_converted_not_garbage(self):
        eng, _ = make_engine()
        eng.process(np.zeros(1280, dtype=np.float32))
        self.assertEqual(eng.model.frames[0].dtype, np.int16)


if __name__ == "__main__":
    unittest.main()
