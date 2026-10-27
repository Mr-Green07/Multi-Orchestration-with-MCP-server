"""Hardware tool: validation, verify-after-act, undo, dry-run, graceful failure.

The real OS backends are replaced by fakes, so these tests describe the contract
of the tool rather than the behaviour of any particular audio device.
"""
from __future__ import annotations

import pytest

import config
from mcp_server import policy
from mcp_server.tools import hardware_controls as hw


class FakeDevice:
    """A controllable volume/brightness device with an observable value."""

    def __init__(self, value=50, mute=False, readback=True):
        self.value = value
        self.mute = mute
        self.readback = readback
        self.set_calls = []

    def install(self, monkeypatch, target):
        def getter():
            if target == "mute":
                return (self.mute if self.readback else None), "fake"
            return (self.value if self.readback else None), "fake"

        def setter(new_value):
            self.set_calls.append(new_value)
            if target == "mute":
                self.mute = bool(new_value)
            else:
                self.value = new_value
            return "fake"

        monkeypatch.setitem(hw.BACKENDS, target, (getter, setter))


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    hw._LAST_CHANGE.clear()
    yield
    hw._LAST_CHANGE.clear()


def test_volume_is_applied_and_verified(monkeypatch):
    device = FakeDevice(value=20)
    device.install(monkeypatch, "volume")

    result = hw.control_hardware("volume", 65)

    assert result["status"] == "success"
    assert result["applied"] is True
    assert result["payload"]["observed"] == 65
    assert result["previous"] == {"value": 20}
    assert device.set_calls == [65]


def test_verify_detects_a_setting_that_did_not_stick(monkeypatch):
    class StuckDevice(FakeDevice):
        def install(self, monkeypatch, target):
            def getter():
                return 20, "stuck"

            def setter(_value):
                return "stuck"

            monkeypatch.setitem(hw.BACKENDS, target, (getter, setter))

    StuckDevice().install(monkeypatch, "volume")
    result = hw.control_hardware("volume", 65)

    assert result["status"] == "success"
    assert result["applied"] is False
    assert result["payload"]["observed"] == 20
    assert "read-back showed 20" in result["summary"]


def test_readback_unavailable_reports_none(monkeypatch):
    FakeDevice(readback=False).install(monkeypatch, "brightness")
    result = hw.control_hardware("brightness", 40)
    assert result["status"] == "success"
    assert result["applied"] is None


@pytest.mark.parametrize("target,value", [
    ("volume", 101), ("volume", -1), ("brightness", 150), ("mute", 5),
])
def test_out_of_range_is_rejected_without_touching_the_device(monkeypatch, target, value):
    device = FakeDevice()
    device.install(monkeypatch, target)
    result = hw.control_hardware(target, value)
    assert result["status"] == "error"
    assert "hardware" in result["summary"].lower()
    assert device.set_calls == []


def test_undo_restores_the_previous_value(monkeypatch):
    device = FakeDevice(value=15)
    device.install(monkeypatch, "volume")
    hw.control_hardware("volume", 80)
    assert device.value == 80

    result = hw.undo_last_change()

    assert result["status"] == "success"
    assert device.value == 15
    assert result["metric_or_action"] == "undo_volume"


def test_undo_without_history_is_an_error():
    result = hw.undo_last_change()
    assert result["status"] == "error"
    assert result["payload"]["code"] == "nothing_to_undo"


def test_dry_run_does_not_touch_the_device(monkeypatch):
    device = FakeDevice()
    device.install(monkeypatch, "volume")
    policy.set_dry_run(True)
    try:
        result = hw.control_hardware("volume", 30)
    finally:
        policy.set_dry_run(False)

    assert result["status"] == "dry_run"
    assert device.set_calls == []
    assert result["payload"]["would_execute"] is True


def test_backend_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setitem(hw.BACKENDS, "brightness",
                        (lambda: (None, "none"), lambda _v: (_ for _ in ()).throw(
                            RuntimeError("No backlight device"))))
    result = hw.control_hardware("brightness", 50)
    assert result["status"] == "error"
    assert "could not be changed" in result["summary"]


def test_read_hardware_state_shape(monkeypatch):
    FakeDevice(value=42).install(monkeypatch, "volume")
    FakeDevice(value=77).install(monkeypatch, "brightness")
    state = hw.read_hardware_state()
    assert state["volume"]["value"] == 42
    assert state["brightness"]["value"] == 77
