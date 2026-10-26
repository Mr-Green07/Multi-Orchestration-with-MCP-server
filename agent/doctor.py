"""agent/doctor.py
===============
Environment diagnostics: ``python -m agent doctor``.

Every check reports pass / warn / fail with the exact reason, because the most
common failure with a local-model agent is not a bug - it is a missing model, a
missing audio backend or a jail the user cannot write to. A failing *optional*
check degrades one capability; a failing *required* check stops the agent.
"""
from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import config
from agent.llm import llm_status
from mcp_server import policy


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True
    hint: str | None = None

    @property
    def level(self) -> str:
        if self.ok:
            return "pass"
        return "fail" if self.required else "warn"


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _check_python() -> Check:
    version = ".".join(str(p) for p in sys.version_info[:3])
    ok = sys.version_info >= (3, 10)
    return Check("python", ok, f"{version} ({platform.python_implementation()})",
                 hint="Python 3.10+ is required; 3.12 is recommended.")


def _check_dependencies() -> list[Check]:
    checks = []
    for module, required, hint in (
        ("psutil", True, "pip install psutil"),
        ("pydantic", True, "pip install pydantic"),
        ("fastmcp", True, "pip install fastmcp"),
        ("llama_cpp", True, "pip install llama-cpp-python"),
    ):
        present = _has_module(module)
        checks.append(Check(f"dependency:{module}", present,
                            "installed" if present else "missing",
                            required=required, hint=hint))
    return checks


def _check_model() -> Check:
    status = llm_status()
    if not status["runtime_installed"]:
        return Check("model", False, "llama.cpp runtime missing", required=True,
                     hint="pip install llama-cpp-python")
    if not status["model_present"]:
        return Check("model", False, f"no GGUF at {status['model_path']}",
                     required=False,
                     hint="Place a Q4_K_M model there or set AGENT_MODEL_PATH.")
    size_gb = Path(status["model_path"]).stat().st_size / (1024 ** 3)
    return Check("model", True,
                 f"{Path(status['model_path']).name} ({size_gb:.1f} GB, "
                 f"n_ctx={status['n_ctx']})")


def _check_jail() -> Check:
    root = Path(config.WORKSPACE_JAIL_ROOT)
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check("workspace jail", True, f"{root} (writable)")
    except OSError as exc:
        return Check("workspace jail", False, f"{root} is not writable: {exc}",
                     required=True, hint="Set WORKSPACE_JAIL_ROOT to a writable path.")


def _check_audit() -> Check:
    try:
        Path(config.AUDIT_DIR).mkdir(parents=True, exist_ok=True)
        probe = Path(config.AUDIT_DIR) / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        state = "appendable" if config.AUDIT_ENABLED else "disabled by env"
        return Check("audit log", True, f"{config.AUDIT_DIR} ({state})")
    except OSError as exc:
        return Check("audit log", False, f"{config.AUDIT_DIR} not writable: {exc}",
                     required=False, hint="Set AGENT_AUDIT_DIR to a writable path.")


def _check_hardware() -> list[Check]:
    from mcp_server.tools.hardware_controls import BACKENDS

    checks = []
    for target, (getter, _setter) in BACKENDS.items():
        try:
            value, backend = getter()
        except Exception as exc:
            checks.append(Check(f"hardware:{target}", False, f"{exc}", required=False))
            continue
        if value is None:
            checks.append(Check(f"hardware:{target}", False,
                                f"no {target} backend on this host",
                                required=False,
                                hint="Windows: pycaw/WMI. Linux: pactl + brightnessctl."))
        else:
            checks.append(Check(f"hardware:{target}", True,
                                f"{target} = {value} (via {backend})", required=False))
    return checks


def _check_desktop() -> list[Check]:
    checks = []
    clipboard_tools = ("pbpaste", "xclip", "xsel", "wl-paste")
    has_clipboard = policy.host_platform() == "win32" or any(
        shutil.which(t) for t in clipboard_tools)
    checks.append(Check("clipboard", has_clipboard,
                        "backend available" if has_clipboard else "no clipboard utility",
                        required=False, hint="Install xclip, xsel or wl-clipboard."))

    screenshot_tools = ("grim", "scrot", "import", "screencapture")
    has_shot = policy.host_platform() == "win32" or _has_module("PIL") or any(
        shutil.which(t) for t in screenshot_tools)
    checks.append(Check("screenshot", has_shot,
                        "backend available" if has_shot else "no screenshot utility",
                        required=False, hint="pip install pillow, or install scrot/grim."))

    has_notify = (policy.host_platform() in {"win32", "darwin"}
                  or shutil.which("notify-send") is not None)
    checks.append(Check("notifications", has_notify,
                        "backend available" if has_notify else "notify-send missing",
                        required=False, hint="Install libnotify-bin."))
    return checks


def _server_tool_names() -> list[str]:
    """List the server's tools from a synchronous context (FastMCP is async)."""
    import asyncio

    from mcp_server.server import mcp

    coroutine = mcp.list_tools()
    try:
        tools = asyncio.run(coroutine)
    except RuntimeError:                     # already inside an event loop
        loop = asyncio.new_event_loop()
        try:
            tools = loop.run_until_complete(coroutine)
        finally:
            loop.close()
    return sorted(tool.name for tool in tools)


def _check_server() -> Check:
    try:
        names = _server_tool_names()
        return Check("mcp server", len(names) > 0,
                     f"{len(names)} tools registered: {', '.join(names[:6])}"
                     + ("..." if len(names) > 6 else ""))
    except Exception as exc:
        return Check("mcp server", False, f"import failed: {exc}", required=True)


def _check_policy() -> Check:
    from mcp_server import security

    token = security.create_confirmation_token("doctor", {"probe": True})
    ok = security.verify_and_consume_token(token, "doctor") is not None
    replay = security.verify_and_consume_token(token, "doctor") is None
    return Check("confirmation tokens", ok and replay,
                 "issue/verify ok, replay blocked" if ok and replay
                 else "token protocol misbehaved")


def run_checks() -> list[Check]:
    checks: list[Check] = [
        _check_python(),
        *_check_dependencies(),
        _check_model(),
        _check_jail(),
        _check_audit(),
        _check_server(),
        _check_policy(),
        *_check_hardware(),
        *_check_desktop(),
    ]
    return checks


def format_checks(checks: list[Check]) -> str:
    icons = {"pass": "[pass]", "warn": "[warn]", "fail": "[fail]"}
    lines = []
    for check in checks:
        lines.append(f"{icons[check.level]:<7} {check.name:<24} {check.detail}")
        if check.hint and not check.ok:
            lines.append(f"        -> {check.hint}")
    failed_required = [c for c in checks if not c.ok and c.required]
    warns = [c for c in checks if not c.ok and not c.required]
    lines.append("")
    lines.append(f"{len(checks)} checks: {len(checks) - len(failed_required) - len(warns)} pass, "
                 f"{len(warns)} warning(s), {len(failed_required)} failure(s)")
    if failed_required:
        lines.append("Required checks failed: the agent cannot run until these are fixed.")
    elif warns:
        lines.append("Warnings only: some capabilities are unavailable, nothing is blocking.")
    return "\n".join(lines)


def main() -> int:
    checks = run_checks()
    print(format_checks(checks))
    return 1 if any(not c.ok and c.required for c in checks) else 0
