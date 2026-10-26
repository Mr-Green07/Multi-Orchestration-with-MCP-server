"""mcp_server/tools/desktop.py
===========================
Desktop-adjacent capabilities: clipboard, screenshot, opening a target,
notifications and media keys.

Every function degrades honestly. If the host has no clipboard utility, no
screenshot tool or no notification daemon, the response is ``status="unsupported"``
with an installation hint - never a stack trace, and never a silent success.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Literal
from urllib.parse import urlparse

import config
from mcp_server import policy
from mcp_server.tools._common import JailViolation, resolve_in_jail, respond, simulate, unsupported

ClipboardAction = Literal["read", "write"]
MediaAction = Literal["play_pause", "next", "previous", "stop"]


def _windll(library: str):
    """``ctypes.windll`` exists only on Windows; resolve it at call time."""
    import ctypes

    return getattr(ctypes, "windll").__getattr__(library)


def _run(argv: list[str], timeout: float = 6.0, input_text: str | None = None):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              shell=False, check=False, input=input_text)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None if isinstance(exc, FileNotFoundError) else exc


# --------------------------------------------------------------------------- clipboard
def clipboard(action: ClipboardAction, text: str | None = None,
              correlation_id: str | None = None) -> dict:
    tool = "clipboard"
    platform = policy.host_platform()

    if action == "read":
        if platform == "win32":
            try:
                import ctypes

                user32 = _windll("user32")
                if not user32.OpenClipboard(None):
                    raise RuntimeError("clipboard is busy")
                try:
                    handle = user32.GetClipboardData(13)      # CF_UNICODETEXT
                    if not handle:
                        return respond(tool=tool, action="clipboard_read", status="success",
                                       summary="Clipboard is empty.",
                                       payload={"text": ""}, correlation_id=correlation_id)
                    value = ctypes.c_wchar_p(handle).value or ""
                    return respond(tool=tool, action="clipboard_read", status="success",
                                   summary=f"Read {len(value)} characters from the clipboard.",
                                   payload={"text": value[: config.MAX_READ_CHARS]},
                                   correlation_id=correlation_id)
                finally:
                    user32.CloseClipboard()
            except Exception as exc:
                return unsupported(tool, "clipboard_read",
                                   f"Clipboard read failed: {exc}")
        for binary, argv in (("pbpaste", ["pbpaste"]),
                             ("wl-paste", ["wl-paste", "--no-newline"]),
                             ("xclip", ["xclip", "-selection", "clipboard", "-o"]),
                             ("xsel", ["xsel", "--clipboard", "--output"])):
            if shutil.which(binary):
                proc = _run(argv)
                value = proc.stdout if proc is not None and proc.returncode == 0 else ""
                return respond(tool=tool, action="clipboard_read", status="success",
                               summary=f"Read {len(value)} characters from the clipboard.",
                               payload={"text": value[: config.MAX_READ_CHARS],
                                        "backend": binary},
                               correlation_id=correlation_id)
        return unsupported(tool, "clipboard_read", "No clipboard backend is available.",
                           hint="Install xclip, xsel or wl-clipboard.")

    # ---- write
    if not text:
        return respond(tool=tool, action="clipboard_write", status="error",
                       summary="Nothing to copy: 'text' is required.",
                       payload={"code": "missing_text"}, correlation_id=correlation_id)
    if policy.dry_run_enabled():
        return simulate(tool=tool, action="clipboard_write",
                        summary=f"{len(text)} characters would be copied.",
                        payload={"characters": len(text)}, correlation_id=correlation_id)

    if platform == "win32":
        try:
            import ctypes

            user32 = _windll("user32")
            kernel32 = _windll("kernel32")
            if not user32.OpenClipboard(None):
                raise RuntimeError("clipboard is busy")
            try:
                user32.EmptyClipboard()
                data = ctypes.create_unicode_buffer(text)
                kernel32.GlobalAlloc.restype = ctypes.c_void_p
                handle = kernel32.GlobalAlloc(0x0042, ctypes.sizeof(data))
                mem = kernel32.GlobalLock(ctypes.c_void_p(handle))
                ctypes.memmove(mem, data, ctypes.sizeof(data))
                kernel32.GlobalUnlock(ctypes.c_void_p(handle))
                user32.SetClipboardData(13, ctypes.c_void_p(handle))
            finally:
                user32.CloseClipboard()
            return respond(tool=tool, action="clipboard_write", status="success",
                           summary=f"Copied {len(text)} characters to the clipboard.",
                           payload={"characters": len(text)}, correlation_id=correlation_id,
                           applied=True)
        except Exception as exc:
            return unsupported(tool, "clipboard_write", f"Clipboard write failed: {exc}")

    for binary, argv in (("pbcopy", ["pbcopy"]),
                         ("wl-copy", ["wl-copy"]),
                         ("xclip", ["xclip", "-selection", "clipboard"]),
                         ("xsel", ["xsel", "--clipboard", "--input"])):
        if shutil.which(binary):
            proc = _run(argv, input_text=text)
            if proc is not None and getattr(proc, "returncode", 1) == 0:
                return respond(tool=tool, action="clipboard_write", status="success",
                               summary=f"Copied {len(text)} characters to the clipboard.",
                               payload={"characters": len(text), "backend": binary},
                               correlation_id=correlation_id, applied=True)
    return unsupported(tool, "clipboard_write", "No clipboard backend is available.",
                       hint="Install xclip, xsel or wl-clipboard.")


# --------------------------------------------------------------------------- screenshot
def screenshot(relative_path: str = "screenshot.png",
               correlation_id: str | None = None) -> dict:
    tool = "screenshot"
    try:
        target = resolve_in_jail(relative_path)
    except JailViolation as exc:
        return respond(tool=tool, action="screenshot", status="error", summary=str(exc),
                       payload={"code": "jail_violation"}, correlation_id=correlation_id)

    if policy.dry_run_enabled():
        return simulate(tool=tool, action="screenshot",
                        summary=f"A screenshot would be written to {target.name}.",
                        payload={"path": str(target)}, correlation_id=correlation_id)

    target.parent.mkdir(parents=True, exist_ok=True)
    platform = policy.host_platform()

    try:
        if platform == "win32":
            try:
                from PIL import ImageGrab
            except ImportError:
                return unsupported(tool, "screenshot", "Pillow is not installed.",
                                   hint="pip install pillow")
            ImageGrab.grab().save(target)
        elif platform == "darwin":
            if shutil.which("screencapture") is None:
                return unsupported(tool, "screenshot", "screencapture is unavailable.")
            proc = _run(["screencapture", "-x", str(target)])
            if proc is None or getattr(proc, "returncode", 1) != 0:
                raise RuntimeError("screencapture failed")
        else:
            command = None
            for binary, argv in (("grim", ["grim", str(target)]),
                                 ("scrot", ["scrot", "-o", "-z", str(target)]),
                                 ("import", ["import", "-window", "root", str(target)])):
                if shutil.which(binary):
                    command = argv
                    break
            if command is None:
                return unsupported(tool, "screenshot",
                                   "No screenshot backend is available.",
                                   hint="Install grim (Wayland), scrot or ImageMagick.")
            proc = _run(command)
            if proc is None or getattr(proc, "returncode", 1) != 0:
                raise RuntimeError("screenshot command failed")
    except Exception as exc:
        return respond(tool=tool, action="screenshot", status="error",
                       summary=f"Screenshot failed: {exc}",
                       payload={"code": "screenshot_failed"}, correlation_id=correlation_id)

    size = target.stat().st_size if target.exists() else 0
    return respond(tool=tool, action="screenshot", status="success",
                   summary=f"Saved screenshot to workspace/{target.name} ({size} bytes).",
                   payload={"path": f"workspace/{target.name}", "bytes": size},
                   correlation_id=correlation_id, applied=size > 0)


# --------------------------------------------------------------------------- open
def open_target(target: str, correlation_id: str | None = None) -> dict:
    """Open a URL or a workspace file/folder with the OS default handler."""
    tool = "open_target"
    if not target:
        return respond(tool=tool, action="open", status="error",
                       summary="Nothing to open: 'target' is required.",
                       payload={"code": "missing_target"}, correlation_id=correlation_id)

    parsed = urlparse(target)
    is_url = bool(parsed.scheme)
    if is_url:
        if parsed.scheme.lower() not in config.ALLOWED_URL_SCHEMES:
            return respond(tool=tool, action="open", status="error",
                           summary=f"URL scheme '{parsed.scheme}' is not allowed.",
                           payload={"code": "scheme_not_allowed",
                                    "allowed": sorted(config.ALLOWED_URL_SCHEMES)},
                           correlation_id=correlation_id)
        path = None
    else:
        try:
            path = resolve_in_jail(target)
        except JailViolation as exc:
            return respond(tool=tool, action="open", status="error", summary=str(exc),
                           payload={"code": "jail_violation"},
                           correlation_id=correlation_id)
        if not path.exists():
            return respond(tool=tool, action="open", status="error",
                           summary=f"There is no such item in the workspace: '{target}'.",
                           payload={"code": "not_found"}, correlation_id=correlation_id)

    if policy.dry_run_enabled():
        return simulate(tool=tool, action="open",
                        summary=f"'{target}' would be opened with the default handler.",
                        payload={"target": target}, correlation_id=correlation_id)

    platform = policy.host_platform()
    try:
        if platform == "win32":
            import os
            getattr(os, "startfile")(str(path) if path else target)  # noqa: S606
            backend = "os.startfile"
        elif platform == "darwin":
            proc = _run(["open", str(path) if path else target])
            backend = "open"
            if proc is None or getattr(proc, "returncode", 1) != 0:
                raise RuntimeError("open failed")
        else:
            proc = _run(["xdg-open", str(path) if path else target])
            backend = "xdg-open"
            if proc is None or getattr(proc, "returncode", 1) != 0:
                raise RuntimeError((getattr(proc, "stderr", "") or "xdg-open failed").strip())
    except Exception as exc:
        return unsupported(tool, "open", f"Could not open the target: {exc}")

    return respond(tool=tool, action="open", status="success",
                   summary=f"Opened '{target}'.",
                   payload={"target": target, "backend": backend},
                   correlation_id=correlation_id, applied=True)


# --------------------------------------------------------------------------- notifications
def notify(title: str = "Agent", message: str = "",
           correlation_id: str | None = None) -> dict:
    tool = "notify"
    platform = policy.host_platform()
    if policy.dry_run_enabled():
        return simulate(tool=tool, action="notify",
                        summary=f"A notification '{title}' would be shown.",
                        payload={"title": title, "message": message},
                        correlation_id=correlation_id)
    try:
        if platform == "win32":
            script = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                "ContentType = WindowsRuntime] > $null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(0);"
                f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{title}'))>$null;"
                f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode('{message}'))>$null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                "'SystemOperator').Show("
                "[Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            proc = _run(["powershell.exe", "-NoProfile", "-Command", script])
            backend = "windows-toast"
        elif platform == "darwin":
            proc = _run(["osascript", "-e",
                         f'display notification "{message}" with title "{title}"'])
            backend = "osascript"
        else:
            if shutil.which("notify-send") is None:
                return unsupported(tool, "notify", "No notification backend is available.",
                                   hint="Install libnotify-bin (notify-send).")
            proc = _run(["notify-send", title, message])
            backend = "notify-send"
        if proc is None or getattr(proc, "returncode", 1) != 0:
            raise RuntimeError(getattr(proc, "stderr", "") or "notification failed")
    except Exception as exc:
        return unsupported(tool, "notify", f"Notification failed: {exc}")
    return respond(tool=tool, action="notify", status="success",
                   summary=f"Notification sent: {title}",
                   payload={"title": title, "backend": backend},
                   correlation_id=correlation_id, applied=True)


# --------------------------------------------------------------------------- media
def media_control(action: MediaAction, correlation_id: str | None = None) -> dict:
    tool = "media_control"
    if policy.dry_run_enabled():
        return simulate(tool=tool, action=action,
                        summary=f"Media '{action}' would be sent.",
                        payload={"action": action}, correlation_id=correlation_id)

    platform = policy.host_platform()
    if platform == "win32":
        key_codes = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}
        try:

            vk = key_codes[action]
            user32 = _windll("user32")
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, 2, 0)
            backend = "win32-keybd_event"
        except Exception as exc:
            return unsupported(tool, action, f"Media key injection failed: {exc}")
    elif platform == "darwin":
        codes = {"play_pause": 16, "next": 17, "previous": 18, "stop": 16}
        proc = _run(["osascript", "-e",
                     f'tell application "System Events" to key code {codes[action]}'])
        backend = "osascript"
        if proc is None or getattr(proc, "returncode", 1) != 0:
            return unsupported(tool, action, "Media control is unavailable on this host.")
    else:
        if shutil.which("playerctl") is None:
            return unsupported(tool, action, "playerctl is not installed.",
                               hint="Install playerctl for media control on Linux.")
        proc = _run(["playerctl", action.replace("_", "-")])
        backend = "playerctl"
        if proc is None or getattr(proc, "returncode", 1) != 0:
            return respond(tool=tool, action=action, status="error",
                           summary="No media player is currently controllable.",
                           payload={"code": "no_player", "backend": backend},
                           correlation_id=correlation_id)
    return respond(tool=tool, action=action, status="success",
                   summary=f"Media action '{action}' sent.",
                   payload={"action": action, "backend": backend},
                   correlation_id=correlation_id, applied=True)
