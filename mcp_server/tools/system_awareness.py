"""mcp_server/tools/system_awareness.py
=====================================
Read-only "what is actually on this machine" queries.

Every function here is deliberately *observational*:

* it never changes a service, a startup entry or a setting;
* it degrades to ``status="unsupported"`` with a ``user_hint`` instead of raising
  when the platform has no equivalent (macOS, a container, a stripped-down Linux);
* the expensive variants (``apps``, ``errors``) are capped and cached, because a
  ``winget list`` or a 24-hour event-log query can take seconds.

Windows is the primary target (PowerShell), with a Linux fallback (systemctl,
journalctl, dpkg/flatpak, wmctrl) so the whole feature set stays demonstrable on a
developer box. Nothing here is ever fed to ``shell=True``: argv lists only.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import config
from mcp_server.tools._common import respond, unsupported

CATEGORIES = ("services", "startup", "apps", "errors", "windows")

#: Query results change slowly and can be costly; keep them for a short while.
CACHE_TTL_SECONDS = 120.0
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


# --------------------------------------------------------------------------- helpers
def _run(argv: list[str], timeout: float = 12.0) -> tuple[int, str, str]:
    """Run a read-only command without a shell. Returns (returncode, out, err)."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              check=False)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{argv[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]} timed out after {timeout:.0f}s"
    except OSError as exc:
        return 126, "", str(exc)


def _powershell(script: str, timeout: float = 15.0) -> tuple[bool, list[dict[str, Any]] | str]:
    """Run a PowerShell snippet that emits JSON; returns parsed rows or an error."""
    rc, out, err = _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout
    )
    if rc != 0:
        return False, (err or out or "powershell failed").strip()[:300]
    text = out.strip()
    if not text:
        return True, []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False, "PowerShell returned data that was not JSON"
    if isinstance(data, dict):
        data = [data]
    return True, [row for row in data if isinstance(row, dict)]


def _cached(key: str, builder) -> dict[str, Any]:
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        payload = dict(hit[1])
        payload["cached"] = True
        return payload
    fresh: dict[str, Any] = builder()
    _CACHE[key] = (now, fresh)
    return dict(fresh)


def clear_cache() -> None:
    """Drop cached inventory results (used by tests and after an install)."""
    _CACHE.clear()


# --------------------------------------------------------------------------- services
def _services_windows() -> tuple[bool, list[dict[str, Any]] | str]:
    script = (
        "Get-Service | ForEach-Object { "
        "[pscustomobject]@{ name = $_.Name; state = \"$($_.Status)\"; "
        "start_mode = \"$($_.StartType)\"; display = $_.DisplayName } } | "
        "Sort-Object name | ConvertTo-Json -Compress"
    )
    return _powershell(script)


def _services_linux() -> tuple[bool, list[dict[str, Any]] | str]:
    rc, out, err = _run(["systemctl", "list-units", "--type=service",
                         "--all", "--no-pager", "--no-legend", "--plain"])
    if rc != 0:
        return False, (err or "systemctl unavailable").strip()[:300]
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        unit = parts[0]
        rows.append({
            "name": unit.removesuffix(".service"),
            "state": parts[3],
            "active": parts[2],
            "display": " ".join(parts[4:]) or unit,
        })
    return True, rows


def _services() -> dict[str, Any]:
    if os.name == "nt":
        ok, rows = _services_windows()
    elif os.uname().sysname == "Darwin":            # pragma: no cover - platform
        return unsupported(
            tool="system_inventory", action="services",
            detail="Service enumeration is not implemented on macOS in this build.",
            hint="Use 'launchctl list' manually; a separate backend is required.",
        )
    else:
        ok, rows = _services_linux()

    if not ok or not isinstance(rows, list):
        return unsupported(tool="system_inventory", action="services",
                           detail=f"Could not enumerate services: {rows}",
                           hint="Windows needs PowerShell; Linux needs systemctl.")
    running = [r for r in rows if str(r.get("state", "")).lower() in {"running", "active"}]
    return {
        "summary": f"{len(rows)} services, {len(running)} running.",
        "payload": {"total": len(rows), "running": len(running),
                    "services": rows[: config.MAX_INVENTORY_ROWS]},
        "applied": None,
    }


# --------------------------------------------------------------------------- startup
def _startup_windows() -> tuple[bool, list[dict[str, Any]] | str]:
    script = (
        "$paths = @("
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',"
        "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run');"
        "foreach ($p in $paths) {"
        "  if (Test-Path $p) {"
        "    $item = Get-ItemProperty $p;"
        "    $item.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } |"
        "      ForEach-Object { [pscustomobject]@{ name = $_.Name; "
        "command = \"$($_.Value)\"; scope = $p } } } } | "
        "ConvertTo-Json -Compress"
    )
    return _powershell(script)


def _desktop_entries(directory: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not directory.is_dir():
        return rows
    for entry in sorted(directory.glob("*.desktop"))[: config.MAX_INVENTORY_ROWS]:
        name, command, enabled = entry.stem, "", True
        try:
            for line in entry.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Name=") and not command:
                    name = line.split("=", 1)[1].strip()
                elif line.startswith("Exec="):
                    command = line.split("=", 1)[1].strip()
                elif line.startswith("Hidden=true"):
                    enabled = False
        except OSError:
            continue
        rows.append({"name": name, "command": command[:200],
                     "scope": "autostart", "enabled": enabled})
    return rows


def _startup() -> dict[str, Any]:
    if os.name == "nt":
        ok, rows = _startup_windows()
        if not ok:
            return unsupported(tool="system_inventory", action="startup",
                               detail=f"Could not read startup entries: {rows}",
                               hint="Startup entries are read from the HKCU/HKLM Run keys.")
        rows = rows or []
    else:
        rows = _desktop_entries(Path.home() / ".config" / "autostart")
        rows += _desktop_entries(Path("/etc/xdg/autostart"))
        rc, out, _ = _run(["systemctl", "--user", "list-unit-files", "--type=service",
                           "--no-pager", "--no-legend"])
        if rc == 0:
            for line in out.splitlines()[: config.MAX_INVENTORY_ROWS]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "enabled":
                    rows.append({"name": parts[0], "command": "systemd user unit",
                                 "scope": "systemd-user", "enabled": True})
    return {
        "summary": f"{len(rows)} startup item(s) found.",
        "payload": {"total": len(rows), "items": rows[: config.MAX_INVENTORY_ROWS]},
        "applied": None,
    }


# --------------------------------------------------------------------------- apps
def _apps_windows() -> tuple[bool, list[dict[str, Any]] | str]:
    script = (
        "$keys = @("
        "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*');"
        "Get-ItemProperty $keys -ErrorAction SilentlyContinue |"
        "  Where-Object { $_.DisplayName } |"
        "  ForEach-Object { [pscustomobject]@{ name = $_.DisplayName; "
        "version = \"$($_.DisplayVersion)\"; publisher = \"$($_.Publisher)\" } } |"
        "  Sort-Object name -Unique | ConvertTo-Json -Compress"
    )
    return _powershell(script, timeout=20.0)


def _apps_linux() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rc, out, _ = _run(["dpkg-query", "-W", "-f=${Package}\\t${Version}\\n"], timeout=20.0)
    if rc == 0:
        for line in out.splitlines()[: config.MAX_INVENTORY_ROWS]:
            parts = line.split("\t")
            if parts and parts[0]:
                rows.append({"name": parts[0],
                             "version": parts[1] if len(parts) > 1 else "",
                             "publisher": "dpkg"})
    if not rows:
        rc, out, _ = _run(["rpm", "-qa", "--qf", "%{NAME}\\t%{VERSION}\\n"], timeout=20.0)
        if rc == 0:
            for line in out.splitlines()[: config.MAX_INVENTORY_ROWS]:
                parts = line.split("\t")
                if parts and parts[0]:
                    rows.append({"name": parts[0],
                                 "version": parts[1] if len(parts) > 1 else "",
                                 "publisher": "rpm"})
    return rows


def _apps() -> dict[str, Any]:
    def build() -> dict[str, Any]:
        if os.name == "nt":
            ok, rows = _apps_windows()
            if not ok:
                return {"status": "unsupported", "detail": rows}
            rows = rows or []
        else:
            rows = _apps_linux()
        return {"summary": f"{len(rows)} installed application(s) visible.",
                "payload": {"total": len(rows),
                            "applications": rows[: config.MAX_INVENTORY_ROWS]},
                "applied": None}

    built: dict[str, Any] = _cached("apps", build)
    if built.get("status") == "unsupported":
        return unsupported(tool="system_inventory", action="apps",
                           detail=f"Could not list installed applications: {built['detail']}",
                           hint="Windows: registry Uninstall keys. Linux: dpkg or rpm.")
    payload = dict(built["payload"])
    if built.get("cached"):
        payload["cached"] = True
    return {"status": "success", "summary": built["summary"], "payload": payload,
            "applied": None}


# --------------------------------------------------------------------------- errors
def _errors_windows(hours: int) -> tuple[bool, list[dict[str, Any]] | str]:
    script = (
        f"$since = (Get-Date).AddHours(-{hours});"
        "Get-WinEvent -FilterHashtable @{LogName='System','Application';"
        "Level=1,2; StartTime=$since} -MaxEvents "
        f"{config.MAX_INVENTORY_ROWS} -ErrorAction SilentlyContinue |"
        "  ForEach-Object { [pscustomobject]@{ time = $_.TimeCreated.ToString('s');"
        " level = \"$($_.LevelDisplayName)\"; source = $_.ProviderName;"
        " id = $_.Id; message = \"$($_.Message)\".Substring(0, "
        "[Math]::Min(160, \"$($_.Message)\".Length)) } } |"
        "  ConvertTo-Json -Compress"
    )
    return _powershell(script, timeout=25.0)


def _errors_linux(hours: int) -> tuple[bool, list[dict[str, Any]] | str]:
    rc, out, err = _run(
        ["journalctl", "-q", "-p", "3", "--since", f"-{hours}h", "--no-pager",
         "-o", "short-iso", "-n", str(config.MAX_INVENTORY_ROWS)],
        timeout=20.0,
    )
    # journalctl exits non-zero when it cannot read every source (common in
    # containers) but still prints the lines it *can* see, so parse first.
    if rc != 0 and not out.strip():
        return False, (err or "journalctl unavailable").strip()[:300]
    rows = []
    for line in out.splitlines():
        if not line.strip() or line.startswith("--"):
            continue
        rows.append({"time": line[:19], "level": "error",
                     "message": line[20:200].strip()})
    return True, rows


def _errors(hours: int) -> dict[str, Any]:
    hours = max(1, min(int(hours), 168))
    if os.name == "nt":
        ok, rows = _errors_windows(hours)
        source = "Windows Event Log"
    else:
        ok, rows = _errors_linux(hours)
        source = "journalctl"
    if not ok:
        return unsupported(tool="system_inventory", action="errors",
                           detail=f"Could not read recent errors: {rows}",
                           hint="Windows needs the Event Log; Linux needs journalctl.")
    rows = rows or []
    return {
        "summary": f"{len(rows)} error event(s) in the last {hours}h from {source}.",
        "payload": {"hours": hours, "source": source, "total": len(rows),
                    "events": rows[: config.MAX_INVENTORY_ROWS]},
        "applied": None,
    }


# --------------------------------------------------------------------------- windows
def _windows_windows() -> tuple[bool, list[dict[str, Any]] | str]:
    script = (
        "Get-Process | Where-Object { $_.MainWindowTitle } |"
        "  ForEach-Object { [pscustomobject]@{ pid = $_.Id; process = $_.ProcessName;"
        " title = $_.MainWindowTitle } } | ConvertTo-Json -Compress"
    )
    return _powershell(script)


def _windows_linux() -> tuple[bool, list[dict[str, Any]] | str]:
    for argv, parser in (
        (["wmctrl", "-lp"], "wmctrl"),
        (["xdotool", "search", "--onlyvisible", "--name", ""], "xdotool"),
    ):
        rc, out, err = _run(argv, timeout=6.0)
        if rc != 0:
            continue
        rows = []
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            rows.append({"pid": int(parts[2]) if parts[2].isdigit() else None,
                         "process": parts[3].split(" - ")[-1][:60],
                         "title": parts[3][:160]})
        return True, rows
    return False, "no window tool (install wmctrl or xdotool)"


def _windows() -> dict[str, Any]:
    if os.name == "nt":
        ok, rows = _windows_windows()
    else:
        ok, rows = _windows_linux()
    if not ok:
        return unsupported(tool="system_inventory", action="windows",
                           detail=f"Could not list open windows: {rows}",
                           hint="Windows uses MainWindowTitle; Linux needs "
                                "wmctrl or xdotool.")
    rows = rows or []
    return {
        "summary": f"{len(rows)} window(s) with a visible title.",
        "payload": {"total": len(rows), "windows": rows[: config.MAX_INVENTORY_ROWS]},
        "applied": None,
    }


# --------------------------------------------------------------------------- tool body
_BUILDERS = {
    "services": _services,
    "startup": _startup,
    "apps": _apps,
    "windows": _windows,
}


def system_inventory(kind: str = "services", hours: int = 24,
                     correlation_id: str | None = None) -> dict[str, Any]:
    """Read-only inventory: services, startup, applications, errors or windows."""
    tool = "system_inventory"
    action = str(kind or "services").strip().lower()
    arguments = {"kind": action, "hours": hours}

    if action == "errors":
        outcome = _errors(hours)
    elif action in _BUILDERS:
        outcome = _BUILDERS[action]()
    else:
        return respond(tool=tool, action=action, status="error",
                       summary=f"Unknown inventory '{action}'. Choose one of "
                               f"{', '.join(CATEGORIES)}.",
                       payload={"code": "invalid_category", "retryable": False,
                                "user_hint": f"kind must be one of {', '.join(CATEGORIES)}",
                                "categories": list(CATEGORIES)},
                       arguments=arguments, correlation_id=correlation_id)

    if outcome.get("status") == "unsupported":
        return outcome
    return respond(tool=tool, action=action, status="success",
                   summary=outcome["summary"], payload=outcome["payload"],
                   arguments=arguments, correlation_id=correlation_id,
                   applied=outcome.get("applied"))
