"""mcp_server/tools/hardware_controls.py
=====================================
Volume, mute and display brightness with three properties the first version did
not have:

* **cross-platform backends** - pycaw/WMI on Windows, pactl/amixer/brightnessctl
  or sysfs on Linux, osascript on macOS;
* **verify-after-act** - the value is read back after being written, so the
  response distinguishes "the command was issued" from "the setting changed";
* **undo** - the previous value is captured before every change.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any, Literal

from mcp_server import policy
from mcp_server.tools._common import respond, simulate

HardwareTarget = Literal["volume", "mute", "brightness"]

VALUE_RANGE = {"volume": (0, 100), "mute": (0, 1), "brightness": (0, 100)}
VERIFY_TOLERANCE = {"volume": 2, "mute": 0, "brightness": 2}

#: target -> {"value": previous, "at": monotonic timestamp}
_LAST_CHANGE: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------------- helpers
def _run(argv: list[str], timeout: float = 4.0) -> tuple[int, str, str]:
    """Run a short-lived CLI helper without a shell and without raising."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            shell=False, check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, "", str(exc)


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


# --------------------------------------------------------------------------- volume
def _windows_volume_endpoint():
    """Return the pycaw endpoint volume interface (raises when unavailable)."""
    from pycaw.pycaw import AudioUtilities  # imported lazily: Windows only

    devices = AudioUtilities.GetSpeakers()
    if devices is None:
        raise RuntimeError("No audio output device is available.")
    return devices.EndpointVolume


def _get_volume() -> tuple[int | None, str]:
    platform = policy.host_platform()
    try:
        if platform == "win32":
            return int(round(_windows_volume_endpoint().GetMasterVolumeLevelScalar() * 100)), "pycaw"

        if platform == "darwin":
            code, out, _ = _run(["osascript", "-e", "output volume of (get volume settings)"])
            return (int(out.strip()) if code == 0 and out.strip().isdigit() else None), "osascript"

        if _has("pactl"):
            code, out, _ = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            if code == 0:
                for token in out.replace("/", " ").split():
                    if token.endswith("%"):
                        return int(token.rstrip("%")), "pactl"
        if _has("amixer"):
            code, out, _ = _run(["amixer", "get", "Master"])
            if code == 0:
                for token in out.replace("[", " ").replace("]", " ").split():
                    if token.endswith("%"):
                        return int(token.rstrip("%")), "amixer"
        return None, "none"
    except Exception:
        return None, "error"


def _set_volume(value: int) -> str:
    platform = policy.host_platform()
    if platform == "win32":
        _windows_volume_endpoint().SetMasterVolumeLevelScalar(value / 100.0, None)
        return "pycaw"

    if platform == "darwin":
        code, _, err = _run(["osascript", "-e", f"set volume output volume {value}"])
        if code != 0:
            raise RuntimeError(err.strip() or "osascript failed")
        return "osascript"

    if _has("pactl"):
        code, _, err = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"])
        if code == 0:
            return "pactl"
        raise RuntimeError(err.strip() or "pactl failed")
    if _has("amixer"):
        code, _, err = _run(["amixer", "-q", "sset", "Master", f"{value}%"])
        if code == 0:
            return "amixer"
        raise RuntimeError(err.strip() or "amixer failed")
    raise RuntimeError("No supported audio backend (install pactl or amixer).")


# --------------------------------------------------------------------------- mute
def _get_mute() -> tuple[bool | None, str]:
    platform = policy.host_platform()
    try:
        if platform == "win32":
            return bool(_windows_volume_endpoint().GetMute()), "pycaw"

        if platform == "darwin":
            code, out, _ = _run(["osascript", "-e", "output muted of (get volume settings)"])
            return (out.strip().lower() == "true" if code == 0 else None), "osascript"

        if _has("pactl"):
            code, out, _ = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
            if code == 0:
                return ("yes" in out.lower()), "pactl"
        if _has("amixer"):
            code, out, _ = _run(["amixer", "get", "Master"])
            if code == 0:
                return ("[off]" in out.lower()), "amixer"
        return None, "none"
    except Exception:
        return None, "error"


def _set_mute(value: int) -> str:
    mute = 1 if value > 0 else 0
    platform = policy.host_platform()
    if platform == "win32":
        _windows_volume_endpoint().SetMute(mute, None)
        return "pycaw"

    if platform == "darwin":
        code, _, err = _run(["osascript", "-e",
                             f"set volume output muted {'true' if mute else 'false'}"])
        if code != 0:
            raise RuntimeError(err.strip() or "osascript failed")
        return "osascript"

    if _has("pactl"):
        code, _, err = _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0"])
        if code == 0:
            return "pactl"
        raise RuntimeError(err.strip() or "pactl failed")
    if _has("amixer"):
        code, _, err = _run(["amixer", "-q", "sset", "Master", "mute" if mute else "unmute"])
        if code == 0:
            return "amixer"
        raise RuntimeError(err.strip() or "amixer failed")
    raise RuntimeError("No supported audio backend (install pactl or amixer).")


# --------------------------------------------------------------------------- brightness
def _linux_backlight_dir():
    from pathlib import Path

    base = Path("/sys/class/backlight")
    if not base.exists():
        return None
    candidates = sorted(p for p in base.iterdir() if p.is_dir())
    return candidates[0] if candidates else None


def _get_brightness() -> tuple[int | None, str]:
    platform = policy.host_platform()
    try:
        if platform == "win32":
            script = ("(Get-CimInstance -Namespace root/WMI "
                      "-ClassName WmiMonitorBrightness).CurrentBrightness")
            code, out, _ = _run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                 "-Command", script])
            return (int(out.strip()) if code == 0 and out.strip().isdigit() else None), "wmi"

        if platform == "darwin":
            return None, "unsupported"      # macOS needs private APIs; reported honestly

        if _has("brightnessctl"):
            code, out, _ = _run(["brightnessctl", "get"])
            code2, out2, _ = _run(["brightnessctl", "max"])
            if code == 0 and code2 == 0 and out2.strip().isdigit():
                return int(round(int(out.strip()) / max(int(out2.strip()), 1) * 100)), "brightnessctl"
        device = _linux_backlight_dir()
        if device is not None:
            current = int((device / "brightness").read_text().strip())
            maximum = int((device / "max_brightness").read_text().strip())
            return int(round(current / max(maximum, 1) * 100)), "sysfs"
        return None, "none"
    except Exception:
        return None, "error"


def _set_brightness(value: int) -> str:
    platform = policy.host_platform()
    if platform == "win32":
        script = (
            "$ErrorActionPreference = 'Stop'; "
            "$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods; "
            "if (-not $m) { throw 'Brightness control unavailable' }; "
            f"$m | ForEach-Object {{ Invoke-CimMethod -InputObject $_ -MethodName WmiSetBrightness "
            f"-Arguments @{{Timeout=1; Brightness={value}}} | Out-Null }}; Write-Output 'OK'"
        )
        code, out, err = _run(["powershell.exe", "-NoProfile", "-NonInteractive",
                               "-Command", script], timeout=8.0)
        if code != 0 or "OK" not in out:
            raise RuntimeError(err.strip() or "WMI brightness call failed")
        return "wmi"

    if platform == "darwin":
        raise RuntimeError("Brightness control is unsupported on macOS in this build.")

    if _has("brightnessctl"):
        code, _, err = _run(["brightnessctl", "set", f"{value}%"])
        if code == 0:
            return "brightnessctl"
        raise RuntimeError(err.strip() or "brightnessctl failed")
    device = _linux_backlight_dir()
    if device is not None:
        maximum = int((device / "max_brightness").read_text().strip())
        target = max(1, int(round(maximum * value / 100.0)))
        (device / "brightness").write_text(str(target), encoding="ascii")
        return "sysfs"
    raise RuntimeError("No backlight device and brightnessctl is not installed.")


# --------------------------------------------------------------------------- registry
Backend = tuple[Callable[[], tuple[Any, str]], Callable[[int], str]]

BACKENDS: dict[str, Backend] = {
    "volume": (_get_volume, _set_volume),                 # type: ignore[dict-item]
    "mute": (_get_mute, _set_mute),                       # type: ignore[dict-item]
    "brightness": (_get_brightness, _set_brightness),     # type: ignore[dict-item]
}


# --------------------------------------------------------------------------- tools
def control_hardware(
    target: HardwareTarget,
    value: int,
    correlation_id: str | None = None,
) -> dict:
    """Set a hardware control, verify it, and remember the previous value."""
    tool = "hardware_control"
    action = f"{target}_control"
    arguments = {"target": target, "value": value}

    low, high = VALUE_RANGE.get(target, (0, 100))
    if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
        return respond(
            tool=tool, action=action, status="error",
            summary=f"Hardware control rejected: value {value!r} is outside {low}-{high} "
                    f"for {target}.",
            payload={"code": "out_of_range", "target": target, "allowed": [low, high]},
            arguments=arguments, correlation_id=correlation_id,
        )

    if policy.dry_run_enabled():
        return simulate(
            tool=tool, action=action,
            summary=f"{target} would be set to {value}.",
            payload={"target": target, "requested": value},
            arguments=arguments, correlation_id=correlation_id,
        )

    getter, setter = BACKENDS[target]
    previous, backend = getter()

    try:
        applied_backend = setter(value)
    except Exception as exc:
        text = str(exc).lower()
        elevation = policy.looks_like_elevation_error(text)
        if elevation:
            refusal = policy.elevation_refusal(target)
            return respond(
                tool=tool, action=action, status="error",
                summary=f"{refusal['message']} ({exc})",
                payload=refusal,
                arguments=arguments, correlation_id=correlation_id, applied=False,
            )
        hint = None
        if "backend" in text or "not installed" in text or "unsupported" in text:
            hint = ("This host has no controllable audio/display device. "
                    "Run `python -m agent doctor` to see which backend is missing.")
        return respond(
            tool=tool, action=action, status="error",
            summary=f"The hardware setting could not be changed: {exc}",
            payload={"code": "operation_failed", "target": target, "hint": hint},
            arguments=arguments, correlation_id=correlation_id, applied=False,
        )

    # ---- verify after act
    observed, _ = getter()
    tolerance = VERIFY_TOLERANCE.get(target, 2)
    if observed is None:
        applied = None                       # read-back unsupported on this backend
        verified_note = "read-back unavailable"
    else:
        expected = bool(value) if target == "mute" else value
        applied = abs(observed - int(expected)) <= tolerance if target != "mute" else bool(observed) == bool(expected)
        verified_note = f"read back {observed}"

    if previous is not None:
        _LAST_CHANGE[target] = {"value": previous, "at": time.monotonic()}

    payload = {
        "target": target,
        "requested": value,
        "observed": observed,
        "backend": applied_backend or backend,
        "note": verified_note,
    }
    return respond(
        tool=tool, action=action, status="success",
        summary=(f"{target.capitalize()} set to {value}"
                 + (f" and verified ({verified_note})." if applied else
                    f"; read-back showed {observed}.")),
        payload=payload,
        arguments=arguments,
        correlation_id=correlation_id,
        applied=applied,
        previous={"value": previous} if previous is not None else None,
    )


def undo_last_change(correlation_id: str | None = None) -> dict:
    """Restore the most recent hardware change, if one was recorded."""
    tool = "hardware_undo"
    if not _LAST_CHANGE:
        return respond(
            tool=tool, action="undo", status="error",
            summary="There is no recorded hardware change to undo.",
            payload={"code": "nothing_to_undo"}, correlation_id=correlation_id,
        )
    target = max(_LAST_CHANGE, key=lambda k: _LAST_CHANGE[k]["at"])
    restore = int(_LAST_CHANGE.pop(target)["value"])
    result = control_hardware(target, restore, correlation_id=correlation_id)  # type: ignore[arg-type]
    result["metric_or_action"] = f"undo_{target}"
    result["summary"] = f"Restored {target} to its previous value ({restore})."
    return result


def read_hardware_state() -> dict[str, Any]:
    """Snapshot of every controllable value; used by ``machine_health``."""
    state: dict[str, Any] = {}
    for target, (getter, _setter) in BACKENDS.items():
        value, backend = getter()
        state[target] = {"value": value, "backend": backend}
    return state
