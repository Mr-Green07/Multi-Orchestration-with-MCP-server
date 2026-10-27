"""mcp_server/tools/lifecycle.py
=============================
Application lifecycle: list, launch and (with authorisation) terminate.

Three things changed from the first version:

* launching uses an argv list resolved from ``config.ALLOWED_APPS`` and never a
  shell string, so nothing model-supplied can reach a shell;
* termination is genuinely two-phase: the first call issues a single-use token,
  the second executes. The protected-process denylist is checked *before* a
  token is ever issued;
* every launch is verified by looking for the process afterwards, so "launched"
  means the process exists rather than "Popen did not raise".
"""
from __future__ import annotations

import shutil
import subprocess
import time
from enum import Enum
from typing import Any, Literal

import config
from mcp_server import policy
from mcp_server.security import create_confirmation_token, verify_and_consume_token
from mcp_server.tools._common import respond, simulate


class AllowedApps(str, Enum):
    VSCODE = "vscode"
    BROWSER = "browser"
    TERMINAL = "terminal"
    CALCULATOR = "calculator"
    EXPLORER = "explorer"
    NOTEPAD = "notepad"


LifecycleAction = Literal["launch", "list_running", "request_kill"]


# --------------------------------------------------------------------------- listing
def _process_snapshot(sample_seconds: float = 0.1) -> list[dict[str, Any]]:
    """One pass over the process table with a short CPU sample."""
    import psutil

    procs = list(psutil.process_iter(["pid", "name", "memory_percent"]))
    for proc in procs:                       # prime the CPU counters
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if sample_seconds:
        time.sleep(sample_seconds)
    rows = []
    for proc in procs:
        try:
            info = proc.info
            rows.append({
                "pid": info["pid"],
                "name": info.get("name") or "?",
                "memory_percent": round(float(info.get("memory_percent") or 0.0), 2),
                "cpu_percent": round(proc.cpu_percent(None), 1),
                "protected": policy.is_protected_name(info.get("name")),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


def list_running(limit: int = 10, sort: str = "memory") -> dict:
    rows = _process_snapshot()
    key = "cpu_percent" if sort == "cpu" else "memory_percent"
    rows = [r for r in rows if r[key] > 0]
    rows.sort(key=lambda r: (r[key], r["memory_percent"]), reverse=True)
    top = rows[: max(1, min(limit, 25))]
    return respond(
        tool="app_lifecycle", action="list_running", status="success",
        summary=f"Retrieved top {len(top)} active processes by {sort}.",
        payload={"processes": top, "count": len(top), "sorted_by": sort},
    )


# --------------------------------------------------------------------------- launch
def _binary_exists(argv: list[str]) -> tuple[bool, str]:
    head = argv[0]
    if shutil.which(head):
        return True, head
    if head in {"cmd", "cmd.exe"}:
        return True, head
    return False, head


def launch_app(app_name: str, correlation_id: str | None = None,
               arguments: dict[str, Any] | None = None,
               confirmation_token: str | None = None) -> dict:
    tool = "app_lifecycle"
    action = "launch_app"
    args = arguments or {"action": "launch", "app_name": app_name}
    try:
        argv = policy.resolve_app_argv(app_name)
    except policy.PolicyError as exc:
        return respond(tool=tool, action=action, status="error", summary=str(exc),
                       payload={"code": "app_not_allowed",
                                "allowed": sorted(config.ALLOWED_APPS)},
                       arguments=args, correlation_id=correlation_id)

    if policy.dry_run_enabled():
        return simulate(tool=tool, action=action,
                        summary=f"{app_name} would be launched as {argv}.",
                        payload={"app": app_name, "argv": argv},
                        arguments=args, correlation_id=correlation_id)

    # Optional stricter posture: ask before launching even an allowlisted app.
    if config.REQUIRE_LAUNCH_APPROVAL and not confirmation_token:
        token = create_confirmation_token(f"launch:{app_name}", {"app": app_name})
        return respond(
            tool=tool, action=action, status="requires_confirmation",
            summary=f"Launching {app_name} requires confirmation.",
            payload={"app": app_name, "argv": argv,
                     "warning": "A new application window will open."},
            arguments=args, correlation_id=correlation_id,
            confirmation_token=token, applied=False,
        )
    if config.REQUIRE_LAUNCH_APPROVAL and confirmation_token:
        if not verify_and_consume_token(confirmation_token,
                                        expected_action=f"launch:{app_name}"):
            return respond(tool=tool, action=action, status="error",
                           summary="Invalid or expired confirmation token; nothing was launched.",
                           payload={"code": "bad_token"}, arguments=args,
                           correlation_id=correlation_id, applied=False)

    exists, head = _binary_exists(argv)
    if not exists:
        return respond(
            tool=tool, action=action, status="error",
            summary=f"Cannot launch {app_name}: '{head}' was not found on PATH.",
            payload={"code": "binary_missing", "app": app_name, "missing": head,
                     "hint": "Install the application or add it to PATH, then retry."},
            arguments=args, correlation_id=correlation_id, applied=False,
        )

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, shell=False, close_fds=True,
            start_new_session=True,
        )
    except Exception as exc:
        return respond(tool=tool, action=action, status="error",
                       summary=f"Failed to launch {app_name}: {exc}",
                       payload={"code": "launch_failed", "app": app_name},
                       arguments=args, correlation_id=correlation_id, applied=False)

    # verify: did anything appear? (bounded, never blocking the caller for long)
    import psutil
    deadline = time.monotonic() + 2.0
    verified = False
    while time.monotonic() < deadline:
        if proc.poll() is None:
            verified = True
            break
        try:
            name = psutil.Process(proc.pid).name()
            verified = bool(name)
            break
        except psutil.Error:
            time.sleep(0.15)

    return respond(
        tool=tool, action=action, status="success",
        summary=f"Launched {app_name}" + (" (process verified)." if verified
                                          else " (process not yet visible)."),
        payload={"launched_app": app_name, "argv": argv, "pid": proc.pid,
                 "verified": verified},
        arguments=args, correlation_id=correlation_id, applied=verified,
    )


# --------------------------------------------------------------------------- kill
def request_kill(pid: int, confirmation_token: str | None = None,
                 correlation_id: str | None = None,
                 arguments: dict[str, Any] | None = None) -> dict:
    """Phase 1 issues a token; phase 2 (valid token) actually terminates."""
    tool = "app_lifecycle"
    action = "request_kill"
    args = arguments or {"action": "request_kill", "pid": pid}

    try:
        policy.assert_terminable(pid)
    except policy.PolicyError as exc:
        return respond(tool=tool, action=action, status="error", summary=str(exc),
                       payload={"code": "protected_process", "pid": pid,
                                "hint": "Protected processes are never terminated."},
                       arguments=args, correlation_id=correlation_id)

    ok, reason = policy.TERMINATION_LIMITER.check()
    if not ok:
        return respond(tool=tool, action=action, status="rate_limited", summary=reason,
                       payload={"code": "rate_limited"}, arguments=args,
                       correlation_id=correlation_id)

    name = policy.process_name_for_pid(pid) or "unknown"

    if policy.dry_run_enabled():
        return simulate(tool=tool, action=action,
                        summary=f"PID {pid} ({name}) would be terminated.",
                        payload={"target_pid": pid, "name": name},
                        arguments=args, correlation_id=correlation_id)

    if not confirmation_token:
        token = create_confirmation_token(f"kill:{pid}", {"pid": pid, "name": name})
        return respond(
            tool=tool, action=action, status="requires_confirmation",
            summary=f"Termination of PID {pid} ({name}) requires explicit confirmation.",
            payload={"target_pid": pid, "name": name, "warning": "Destructive action: "
                     "unsaved work in this application will be lost."},
            arguments=args, correlation_id=correlation_id,
            confirmation_token=token, applied=False,
        )

    verified = verify_and_consume_token(confirmation_token, expected_action=f"kill:{pid}")
    if not verified:
        return respond(tool=tool, action=action, status="error",
                       summary="Invalid or expired confirmation token; nothing was terminated.",
                       payload={"code": "bad_token", "target_pid": pid},
                       arguments=args, correlation_id=correlation_id, applied=False)

    import psutil
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
        policy.TERMINATION_LIMITER.consume()
        gone = not psutil.pid_exists(pid) or not psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        gone = True
    except Exception as exc:
        return respond(tool=tool, action=action, status="error",
                       summary=f"Termination of PID {pid} failed: {exc}",
                       payload={"code": "kill_failed", "target_pid": pid},
                       arguments=args, correlation_id=correlation_id, applied=False)

    return respond(
        tool=tool, action=action, status="success",
        summary=f"Terminated PID {pid} ({name})" + (" and verified it exited."
                                                    if gone else "; process still running."),
        payload={"target_pid": pid, "name": name, "exited": gone},
        arguments=args, correlation_id=correlation_id,
        applied=gone, approval="confirmed",
    )


def execute_app_lifecycle(
    action: LifecycleAction,
    app_name: str | None = None,
    pid: int | None = None,
    confirmation_token: str | None = None,
    limit: int = 10,
    sort: str = "memory",
    correlation_id: str | None = None,
) -> dict:
    tool = "app_lifecycle"
    arguments = {"action": action, "app_name": app_name, "pid": pid, "limit": limit,
                 "sort": sort}

    if action == "list_running":
        return list_running(limit=limit, sort=sort)

    if action == "launch":
        if not app_name:
            return respond(tool=tool, action="launch_app", status="error",
                           summary="Missing 'app_name' parameter for launch action.",
                           payload={"error": "app_name required",
                                    "allowed": sorted(config.ALLOWED_APPS)},
                           arguments=arguments, correlation_id=correlation_id)
        return launch_app(app_name, correlation_id=correlation_id,
                          arguments=arguments, confirmation_token=confirmation_token)

    if action == "request_kill":
        if not pid:
            return respond(tool=tool, action="request_kill", status="error",
                           summary="Missing 'pid' parameter for process termination.",
                           payload={"error": "pid required"},
                           arguments=arguments, correlation_id=correlation_id)
        return request_kill(pid, confirmation_token=confirmation_token,
                            correlation_id=correlation_id, arguments=arguments)

    return respond(tool=tool, action="app_lifecycle", status="error",
                   summary="Unsupported application lifecycle action.",
                   payload={"error": "invalid action"}, arguments=arguments,
                   correlation_id=correlation_id)
