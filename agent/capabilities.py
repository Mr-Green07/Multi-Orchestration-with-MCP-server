"""agent/capabilities.py
======================
The startup "capability card": what this agent can and cannot touch on *this*
machine, in plain English, before it does anything.

The card is assembled from live probes (the same ones ``agent doctor`` uses) and
from the server's own tool registry, so it cannot drift out of date: if a tool is
added it appears here, and if a backend is missing the line says so instead of the
agent failing later with a stack trace.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Any

import config
from mcp_server import policy

OK, WARN, OFF = "ok", "warn", "off"


@dataclass
class Capability:
    """One human-readable line of the card."""

    name: str
    state: str            # ok | warn | off
    detail: str


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _hardware_capabilities() -> list[Capability]:
    lines = []
    if policy.host_platform() == "windows":
        lines.append(Capability("volume / mute", OK, "pycaw (WASAPI)"))
        lines.append(Capability("brightness", OK, "WMI (needs admin on some panels)"))
    else:
        volume = _has("pactl") or _has("amixer")
        lines.append(Capability(
            "volume / mute", OK if volume else OFF,
            "pactl/amixer" if volume else "no pactl or amixer on PATH"))
        bright = _has("brightnessctl") or _has("xrandr")
        lines.append(Capability(
            "brightness", OK if bright else OFF,
            "brightnessctl/xrandr" if bright else "no brightnessctl or xrandr"))
    return lines


def _desktop_capabilities() -> list[Capability]:
    lines = []
    if policy.host_platform() == "windows":
        lines.append(Capability("clipboard", OK, "PowerShell Get/Set-Clipboard"))
        lines.append(Capability("screenshot", OK, "PIL ImageGrab"))
        lines.append(Capability("notifications", OK, "Windows toast"))
    else:
        clip = next((b for b in ("wl-copy", "xclip", "xsel") if _has(b)), None)
        lines.append(Capability(
            "clipboard", OK if clip else OFF,
            clip or "install xclip, xsel or wl-clipboard"))
        shot = next((b for b in ("grim", "scrot", "import", "gnome-screenshot")
                     if _has(b)), None)
        lines.append(Capability("screenshot", OK if shot else OFF,
                               shot or "install grim or scrot"))
        lines.append(Capability(
            "notifications", OK if _has("notify-send") else OFF,
            "notify-send" if _has("notify-send") else "install libnotify-bin"))
    lines.append(Capability(
        "media keys", OK if (policy.host_platform() == "windows" or
                             _has("playerctl")) else OFF,
        "Windows media session" if policy.host_platform() == "windows" else "playerctl"))
    return lines


def _awareness_capabilities() -> list[Capability]:
    lines = []
    windows = policy.host_platform() == "windows"
    if windows:
        lines.append(Capability("services / startup / apps", OK,
                                "PowerShell + registry (read-only)"))
        lines.append(Capability("recent errors", OK, "Windows Event Log (read-only)"))
        lines.append(Capability("open windows", OK, "MainWindowTitle"))
    else:
        has_backend = _has("systemctl") or _has("dpkg-query")
        lines.append(Capability(
            "services / startup / apps", WARN if has_backend else OFF,
            "systemctl / dpkg-query (read-only, best effort)" if has_backend
            else "no systemctl, dpkg-query or rpm on this host"))
        has_journal = _has("journalctl") and os.path.isdir("/run/systemd/system")
        lines.append(Capability("recent errors", OK if has_journal else OFF,
                               "journalctl (read-only)" if has_journal else
                               "journalctl needs a running systemd journal"))
        window_tool = next((b for b in ("wmctrl", "xdotool") if _has(b)), None)
        lines.append(Capability("open windows", OK if window_tool else OFF,
                               window_tool or "install wmctrl or xdotool"))
    return lines


def _jail_capabilities() -> list[Capability]:
    jail = config.WORKSPACE_JAIL_ROOT
    writable = os.access(jail, os.W_OK) if os.path.exists(jail) else False
    return [
        Capability("file access", OK if writable else WARN,
                   f"only inside {jail}"),
        Capability("read-only extra scopes", OK if config.READ_ONLY_ROOTS else OFF,
                   ", ".join(str(p) for p in config.READ_ONLY_ROOTS) or
                   "none configured (AGENT_READ_ONLY_ROOTS)"),
    ]


def _safety_capabilities() -> list[Capability]:
    lines = [
        Capability("approval gates", OK,
                   "kill, file overwrite, power, launch (opt-in), organise"),
        Capability("protected processes", OK,
                   f"{len(config.PROTECTED_PROCESSES)} names refused"),
        Capability("audit log", OK if config.AUDIT_ENABLED else OFF,
                   str(config.AUDIT_DIR)),
        Capability("dry-run", OK, "on" if policy.dry_run_enabled() else
                   "off (/dry on)"),
        Capability("panic switch", OK, "Ctrl+C or /panic"),
    ]
    battery = policy.battery_state()
    if battery.get("available"):
        lines.append(Capability(
            "battery guard", OK,
            f"{battery['percent']}% "
            f"({'plugged in' if battery['plugged_in'] else 'on battery'}); "
            f"heavy actions refused under {config.BATTERY_GUARD_PERCENT}%"))
    else:
        lines.append(Capability("battery guard", OFF, "no battery on this host"))
    return lines


def _brain_capabilities() -> list[Capability]:
    from agent.llm import llm_status  # local import: model load is lazy

    status = llm_status()
    usable = bool(status.get("usable"))
    if usable:
        detail = f"{config.MODEL_PATH.name} (n_ctx={status.get('n_ctx')})"
    elif not status.get("runtime_installed"):
        detail = "llama-cpp-python not installed; free-form requests are disabled"
    else:
        detail = f"model file missing at {status.get('model_path')}"
    lines = [Capability("language model", OK if usable else OFF, detail),
        Capability("shortcut classifier", OK if config.USE_CLASSIFIER else OFF,
                   "obvious read-only requests skip inference"),
        Capability("conversation memory", OK,
                   f"last {config.MEMORY_MAX_TURNS} turns"),
    ]
    return lines


def capability_card(tool_count: int | None = None) -> str:
    """Render the card as text (also used by ``/capabilities`` in the REPL)."""
    lines: list[Capability] = []
    lines += _brain_capabilities()
    lines += _hardware_capabilities()
    lines += _desktop_capabilities()
    lines += _awareness_capabilities()
    lines += _jail_capabilities()
    lines += _safety_capabilities()

    icons = {OK: "[ok]  ", WARN: "[warn]", OFF: "[--]  "}
    width = max(len(c.name) for c in lines)
    body = "\n".join(f"  {icons.get(c.state, '[?]   ')} {c.name.ljust(width)}  {c.detail}"
                     for c in lines)

    header = "WHAT I CAN TOUCH ON THIS MACHINE"
    if tool_count is not None:
        header += f"  ({tool_count} tools)"
    footer = ("  Read-only questions work without the model. "
              "Anything destructive asks first and is logged.")
    return f"{header}\n{body}\n{footer}"


def card_dict(tool_count: int | None = None) -> dict[str, Any]:
    """Machine-readable form, for tests and for ``--json`` output."""
    groups = {
        "brain": _brain_capabilities(),
        "hardware": _hardware_capabilities(),
        "desktop": _desktop_capabilities(),
        "awareness": _awareness_capabilities(),
        "files": _jail_capabilities(),
        "safety": _safety_capabilities(),
    }
    return {
        "tool_count": tool_count,
        "platform": policy.host_platform(),
        "capabilities": {group: [vars(item) for item in items]
                         for group, items in groups.items()},
    }
