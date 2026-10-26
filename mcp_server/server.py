"""mcp_server/server.py
====================
The FastMCP application. This module is the *only* place where tools are
registered, and it deliberately does no work itself: each function delegates to a
module under ``mcp_server/tools`` and returns the uniform
:class:`~mcp_server.schemas.SystemToolResponse` dictionary.

Two rules hold for every tool below:

1. it returns a dict with the response contract, never raises;
2. it is annotated with the MCP hints a client needs to reason about risk
   (``readOnlyHint`` / ``destructiveHint``).
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, Literal

from fastmcp import FastMCP

import config
from mcp_server import policy
from mcp_server.tools import (
    desktop,
    knowledge,
    lifecycle,
    power,
    routines,
    system_awareness,
    telemetry,
    workspace,
)
from mcp_server.tools._common import respond
from mcp_server.tools.hardware_controls import control_hardware, undo_last_change

logger = logging.getLogger(__name__)

mcp = FastMCP("SystemOperatorServer")


def _safe(tool: str) -> Callable:
    """Never let an unexpected exception escape into the transport."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict:
            # The panic switch is enforced here, at the transport edge, so it holds
            # for every caller - the planner, a slash command, or another client.
            try:
                policy.assert_not_panicking(tool)
            except policy.PanicActive as exc:
                return respond(
                    tool=tool, action=tool, status="cancelled", summary=str(exc),
                    payload={"code": "panic", "retryable": False,
                             "user_hint": "Send /resume (or POST set_panic(false)) "
                                          "to re-enable actions."},
                    applied=False,
                )
            try:
                return dict(fn(*args, **kwargs))
            except Exception as exc:                      # defensive by design
                logger.exception("tool %s failed", tool)
                return respond(
                    tool=tool, action=tool, status="error",
                    summary=f"Tool '{tool}' raised an unexpected error: {exc}",
                    payload={"code": "unexpected_error", "detail": str(exc)[:300]},
                )

        return wrapper

    return decorator


# =========================================================================== read-only
@mcp.tool(annotations={"readOnlyHint": True})
@_safe("system_telemetry")
def system_telemetry(metric: Literal["cpu", "memory", "disk", "battery"]) -> dict:
    """Read a system metric: cpu, memory, disk or battery (read-only)."""
    return telemetry.system_telemetry(metric)


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("machine_health")
def machine_health() -> dict:
    """One-call health check: CPU, RAM, disk, battery, uptime and a verdict."""
    return telemetry.machine_health()


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("top_processes")
def top_processes(limit: int = 8, sort: Literal["memory", "cpu"] = "memory") -> dict:
    """Rank running processes by memory or CPU, including a protected marker."""
    return telemetry.top_processes(limit=limit, sort=sort)


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("disk_inventory")
def disk_inventory() -> dict:
    """Usage for every mounted volume, most-full first."""
    return telemetry.disk_inventory()


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("network_status")
def network_status() -> dict:
    """Interface state and throughput. Sends no packets (no connectivity probe)."""
    return telemetry.network_status()


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("gpu_status")
def gpu_status() -> dict:
    """GPU utilisation and memory via nvidia-smi, when available."""
    return telemetry.gpu_status()


# =========================================================================== hardware
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("hardware_control")
def hardware_control(target: Literal["volume", "mute", "brightness"],
                     value: int) -> dict:
    """Set volume, mute or brightness (0-100; mute 0/1) and verify the result."""
    return control_hardware(target, value)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("hardware_undo")
def hardware_undo() -> dict:
    """Restore the previous value of the last hardware setting that was changed."""
    return undo_last_change()


# =========================================================================== applications
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
@_safe("app_lifecycle")
def app_lifecycle(
    action: Literal["launch", "list_running", "request_kill"],
    app_name: str | None = None,
    pid: int | None = None,
    confirmation_token: str | None = None,
    limit: int = 10,
    sort: Literal["memory", "cpu"] = "memory",
) -> dict:
    """List, launch (allowlisted) or terminate an application.

    ``request_kill`` is two-phase: the first call returns ``requires_confirmation``
    plus a single-use token; call again with that token to execute.
    """
    return lifecycle.execute_app_lifecycle(
        action, app_name=app_name, pid=pid,
        confirmation_token=confirmation_token, limit=limit, sort=sort,
    )


# =========================================================================== workspace
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("workspace_fs")
def workspace_fs(
    action: Literal["list", "read_text", "search", "stat", "tree", "write_text"],
    relative_path: str = "",
    search_query: str | None = None,
    content: str | None = None,
    max_results: int = 20,
    confirmation_token: str | None = None,
) -> dict:
    """Inspect, search or write files strictly inside the sandboxed workspace."""
    return workspace.execute_workspace_fs(
        action, relative_path=relative_path, search_query=search_query,
        content=content, max_results=max_results,
        confirmation_token=confirmation_token,
    )


# =========================================================================== power
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
@_safe("power_session")
def power_session(
    action: Literal["lock_screen", "sleep", "restart", "shutdown"],
    confirmation_token: str | None = None,
) -> dict:
    """Lock, suspend, restart or shut down. Destructive actions need a token."""
    return power.execute_power_session(action, confirmation_token=confirmation_token)


# =========================================================================== desktop
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("clipboard")
def clipboard(action: Literal["read", "write"], text: str | None = None) -> dict:
    """Read from or write to the system clipboard."""
    return desktop.clipboard(action, text=text)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("screenshot")
def screenshot(relative_path: str = "screenshot.png") -> dict:
    """Capture the screen into the workspace jail."""
    return desktop.screenshot(relative_path=relative_path)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("open_target")
def open_target(target: str) -> dict:
    """Open a workspace file/folder or an http(s)/mailto URL with the OS handler."""
    return desktop.open_target(target)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("notify")
def notify(title: str = "Agent", message: str = "") -> dict:
    """Show a desktop notification."""
    return desktop.notify(title=title, message=message)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("media_control")
def media_control(action: Literal["play_pause", "next", "previous", "stop"]) -> dict:
    """Send a media key: play/pause, next, previous or stop."""
    return desktop.media_control(action)


# =========================================================================== knowledge
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("remember")
def remember(key: str, value: str, tags: str = "") -> dict:
    """Persist a fact across sessions."""
    return knowledge.remember(key, value, tags=tags)


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("recall")
def recall(query: str | None = None, key: str | None = None,
           limit: int = 5) -> dict:
    """Look up stored facts by key or by free-text query."""
    return knowledge.recall(query=query, key=key, limit=limit)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("forget")
def forget(key: str) -> dict:
    """Soft-delete a stored fact."""
    return knowledge.forget(key)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("save_profile")
def save_profile(name: str, steps: list[dict], description: str = "") -> dict:
    """Save a named multi-step routine (a macro) for later replay."""
    return knowledge.save_profile(name, steps, description=description)


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("list_profiles")
def list_profiles() -> dict:
    """List saved routines."""
    return knowledge.list_profiles()


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("get_profile")
def get_profile(name: str) -> dict:
    """Fetch one saved routine and its steps."""
    return knowledge.get_profile(name)


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("search_documents")
def search_documents(query: str, top_k: int = 5, relative_path: str = "") -> dict:
    """Ask-my-files: rank workspace documents against a query and return snippets."""
    return knowledge.search_documents(query, top_k=top_k, relative_path=relative_path)


@mcp.tool(annotations={"readOnlyHint": True})
@_safe("index_status")
def index_status() -> dict:
    """Report how many workspace documents are indexed for search."""
    return knowledge.index_status()


# =========================================================================== awareness
@mcp.tool(annotations={"readOnlyHint": True})
@_safe("system_inventory")
def system_inventory(
    kind: Literal["services", "startup", "apps", "errors", "windows"] = "services",
    hours: int = 24,
) -> dict:
    """Read-only inventory: services, startup items, installed apps, recent errors
    or open windows. Degrades to ``unsupported`` when the platform has no backend."""
    return system_awareness.system_inventory(kind, hours=hours)


# =========================================================================== routines
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("reminders")
def reminders(
    action: Literal["add", "list", "due", "cancel"] = "list",
    text: str | None = None,
    minutes: int = 20,
    reminder_id: int | None = None,
) -> dict:
    """Persisted reminders: add one, list pending ones, collect due ones, or cancel."""
    return routines.reminders(action, text=text, minutes=minutes,
                             reminder_id=reminder_id)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_safe("focus_mode")
def focus_mode(action: Literal["on", "off", "status"] = "on", level: int = 25) -> dict:
    """Quiet the machine: set volume (and DND where supported); ``off`` restores it."""
    return routines.focus_mode(action, level=level)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
@_safe("organize")
def organize(relative_path: str = "", apply: bool = False,
             confirmation_token: str | None = None) -> dict:
    """Plan a tidy-up of a jail folder; ``apply`` needs a confirmation token.
    Files are moved into sub-folders, never deleted."""
    return routines.organize(relative_path, apply=apply,
                             confirmation_token=confirmation_token)


# =========================================================================== entry point
def server_summary() -> dict[str, Any]:
    """Machine-readable description of the server, used by ``agent doctor``."""
    return {
        "name": "SystemOperatorServer",
        "jail": str(config.WORKSPACE_JAIL_ROOT),
        "platform": policy.host_platform(),
        "dry_run": policy.dry_run_enabled(),
    }


if __name__ == "__main__":
    mcp.run()
