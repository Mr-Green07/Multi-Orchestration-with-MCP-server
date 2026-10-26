"""mcp_server/tools/power.py
=========================
Session and power control: lock, sleep, restart, shutdown.

Layered behaviour:

* ``lock_screen`` and ``sleep`` run immediately but are rate limited;
* ``restart`` and ``shutdown`` are two-phase, guarded by a single-use token that
  is bound to the exact action and expires (see ``mcp_server/security.py``);
* every action passes through a sliding-window rate limiter, so a retry loop
  cannot reboot the machine six times in a minute;
* ``dry_run`` reports the resolved command and executes nothing.
"""
from __future__ import annotations

import subprocess
from typing import Literal

from mcp_server import policy
from mcp_server.security import create_confirmation_token, verify_and_consume_token
from mcp_server.tools._common import respond, simulate, unsupported

PowerAction = Literal["lock_screen", "sleep", "restart", "shutdown"]

DESTRUCTIVE = {"restart", "shutdown"}


def _run(argv: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, shell=False, check=False)
        return proc.returncode, (proc.stderr or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, str(exc)


def _execute(action: PowerAction) -> tuple[bool, str]:
    """Perform the OS call. Returns (ok, detail)."""
    platform = policy.host_platform()

    if action == "lock_screen":
        if platform == "win32":
            code, err = _run(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif platform == "darwin":
            code, err = _run(["pmset", "displaysleepnow"])
        else:
            code, err = _run(["loginctl", "lock-session"])
            if code != 0:
                code, err = _run(["xdg-screensaver", "lock"])
        return code == 0, err

    if action == "sleep":
        if platform == "win32":
            code, err = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                              "Add-Type -AssemblyName System.Windows.Forms; "
                              "[System.Windows.Forms.Application]::SetSuspendState('Suspend',$false,$false)"])
        elif platform == "darwin":
            code, err = _run(["pmset", "sleepnow"])
        else:
            code, err = _run(["systemctl", "suspend"])
            if code != 0:
                code, err = _run(["pm-suspend"])
        return code == 0, err

    if action in DESTRUCTIVE:
        if platform == "win32":
            flag = "/r" if action == "restart" else "/s"
            code, err = _run(["shutdown", flag, "/t", "5"])
        elif platform == "darwin":
            code, err = _run(["osascript", "-e",
                              f'tell app "System Events" to {action}'])
        else:
            code, err = _run(["systemctl", "reboot" if action == "restart" else "poweroff"])
        return code == 0, err

    return False, f"unsupported action: {action}"


def execute_power_session(
    action: PowerAction,
    confirmation_token: str | None = None,
    correlation_id: str | None = None,
) -> dict:
    tool = "power_session"
    arguments = {"action": action}

    ok, reason = policy.POWER_LIMITER.check()
    if not ok:
        return respond(tool=tool, action=action, status="rate_limited", summary=reason,
                       payload={"code": "rate_limited", "action": action},
                       arguments=arguments, correlation_id=correlation_id)

    if policy.dry_run_enabled():
        return simulate(tool=tool, action=action,
                        summary=f"System '{action}' would be requested.",
                        payload={"action": action, "destructive": action in DESTRUCTIVE},
                        arguments=arguments, correlation_id=correlation_id)

    # ---- two-phase destructive actions
    if action in DESTRUCTIVE:
        if not confirmation_token:
            token = create_confirmation_token(action, {"target_action": action})
            return respond(
                tool=tool, action=action, status="requires_confirmation",
                summary=f"System {action} requested. Requires explicit confirmation.",
                payload={"target_action": action,
                         "warning": f"Executing {action} will close all active applications."},
                arguments=arguments, correlation_id=correlation_id,
                confirmation_token=token, applied=False,
            )
        if not verify_and_consume_token(confirmation_token, expected_action=action):
            return respond(tool=tool, action=action, status="error",
                           summary="Invalid or expired confirmation token; nothing was executed.",
                           payload={"code": "bad_token", "action": action},
                           arguments=arguments, correlation_id=correlation_id,
                           applied=False)

    executed, detail = _execute(action)
    if not executed:
        if "not found" in detail.lower() or "no such file" in detail.lower():
            return unsupported(tool, action,
                               f"Power action '{action}' is unavailable on this host.",
                               hint="The required system utility is not installed.")
        return respond(tool=tool, action=action, status="error",
                       summary=f"Failed to execute power action '{action}'.",
                       payload={"code": "power_failed", "detail": detail[:300]},
                       arguments=arguments, correlation_id=correlation_id, applied=False)

    policy.POWER_LIMITER.consume()
    payload = {"action": action,
               "confirmed": action in DESTRUCTIVE,
               "grace_seconds": 5 if action in DESTRUCTIVE else 0,
               "platform": policy.host_platform()}
    return respond(
        tool=tool, action=action, status="success",
        summary=(f"Confirmed. System {action} initiated (5 s grace period)."
                 if action in DESTRUCTIVE else f"Power action '{action}' executed."),
        payload=payload, arguments=arguments, correlation_id=correlation_id,
        applied=True, approval="confirmed" if action in DESTRUCTIVE else "not required",
    )
