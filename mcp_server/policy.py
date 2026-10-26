"""mcp_server/policy.py
====================
Policy decisions that are deliberately independent of the model.

Three things live here, all of them cheap and all of them testable without any
hardware:

* the protected-process denylist (Tier 2),
* the launch allowlist -> argv resolution (Tier 2, no shell strings),
* rate limiting for destructive action classes (Tier 4).

Keeping them out of the tool modules means a tool cannot "forget" a policy check:
the check is applied by the server before the tool body runs.
"""
from __future__ import annotations

import os
import platform
import sys
import threading
import time
from dataclasses import dataclass, field

import config


class PolicyError(Exception):
    """Raised when a request violates policy. Never raised to the model raw."""


# --------------------------------------------------------------------------- processes
def normalise_process_name(name: str | None) -> str:
    return (name or "").strip().lower()


def is_protected_name(name: str | None) -> bool:
    """True when *name* matches an entry on the protected denylist."""
    n = normalise_process_name(name)
    if not n:
        return False
    if n in config.PROTECTED_PROCESSES:
        return True
    # e.g. "MsMpEng.exe (pid 1234)" or a path ending in the executable name
    base = n.replace("\\", "/").rsplit("/", 1)[-1]
    return base in config.PROTECTED_PROCESSES


def process_name_for_pid(pid: int) -> str | None:
    """Best-effort name lookup; returns None when the process is gone."""
    try:
        import psutil

        proc = psutil.Process(pid)
        return str(proc.name())
    except Exception:
        return None


def assert_terminable(pid: int, name: str | None = None) -> None:
    """Raise :class:`PolicyError` if this process must not be terminated."""
    resolved = process_name_for_pid(pid)
    for candidate in (name, resolved):
        if is_protected_name(candidate):
            raise PolicyError(
                f"Refusing to terminate '{candidate}' (pid {pid}): it is on the "
                "protected-process denylist."
            )
    if resolved is None and name is None:
        raise PolicyError(f"No such process: pid {pid}.")


# --------------------------------------------------------------------------- launch
def resolve_app_argv(app_name: str) -> list[str]:
    """Map an allowlisted application name to a concrete argv list."""
    key = (app_name or "").strip().lower()
    if key not in config.ALLOWED_APPS:
        allowed = ", ".join(sorted(config.ALLOWED_APPS))
        raise PolicyError(f"'{app_name}' is not on the launch allowlist. Allowed: {allowed}.")
    per_platform = config.ALLOWED_APPS[key]
    platform_key = "win32" if sys.platform.startswith("win") else (
        "darwin" if sys.platform == "darwin" else "linux")
    argv = per_platform.get(platform_key)
    if not argv:
        raise PolicyError(f"'{app_name}' has no launcher for this platform ({platform_key}).")
    return list(argv)


# --------------------------------------------------------------------------- rate limits
@dataclass
class RateLimiter:
    """Sliding-window limiter with an optional minimum gap between events."""

    name: str
    max_events: int
    window_seconds: float
    min_gap_seconds: float = 0.0
    _events: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._events = [t for t in self._events if t >= cutoff]

    def check(self, now: float | None = None) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` without consuming budget."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            if self._events and self.min_gap_seconds:
                elapsed = now - self._events[-1]
                if elapsed < self.min_gap_seconds:
                    wait = self.min_gap_seconds - elapsed
                    return False, (
                        f"Rate limited: a {self.name} action ran {elapsed:.1f} s ago; "
                        f"wait {wait:.0f} s before the next one."
                    )
            if len(self._events) >= self.max_events:
                oldest = self._events[0]
                wait = self.window_seconds - (now - oldest)
                return False, (
                    f"Rate limited: {self.max_events} {self.name} actions in the last "
                    f"{self.window_seconds / 60:.0f} min; retry in {max(wait, 1):.0f} s."
                )
            return True, ""

    def consume(self, now: float | None = None) -> tuple[bool, str]:
        ok, reason = self.check(now)
        if ok:
            with self._lock:
                self._events.append(time.monotonic() if now is None else now)
        return ok, reason

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


POWER_LIMITER = RateLimiter(
    name="power",
    max_events=config.POWER_RATE_LIMIT.max_events,
    window_seconds=config.POWER_RATE_LIMIT.window_seconds,
    min_gap_seconds=config.POWER_RATE_LIMIT.min_gap_seconds,
)
TERMINATION_LIMITER = RateLimiter(
    name="process termination",
    max_events=config.TERMINATION_RATE_LIMIT.max_events,
    window_seconds=config.TERMINATION_RATE_LIMIT.window_seconds,
)

ALL_LIMITERS = (POWER_LIMITER, TERMINATION_LIMITER)


def reset_all_limits() -> None:
    for limiter in ALL_LIMITERS:
        limiter.reset()


# --------------------------------------------------------------------------- dry run
def dry_run_enabled() -> bool:
    """Read the flag at call time so ``--dry-run`` can be toggled at runtime."""
    return bool(config.DRY_RUN)


def set_dry_run(enabled: bool) -> None:
    config.DRY_RUN = bool(enabled)


def host_platform() -> str:
    return "win32" if sys.platform.startswith("win") else (
        "darwin" if sys.platform == "darwin" else "linux")


def platform_label() -> str:
    return f"{platform.system()} {platform.release()}".strip()


# --------------------------------------------------------------------- elevation
#: Substrings that mean "Windows said no because you are not elevated".
_ELEVATION_MARKERS = (
    "access is denied", "access denied", "requires elevation", "elevated",
    "privilege", "permission denied", "errno 13", "unauthorized", "0x80070005",
)


def is_admin() -> bool:
    """True when the current process can already perform privileged operations."""
    try:
        if os.name == "nt":
            import ctypes

            return bool(getattr(ctypes, "windll").shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def looks_like_elevation_error(text: str) -> bool:
    lowered = (text or "").lower()
    if any(marker in lowered for marker in _ELEVATION_MARKERS):
        return True
    # A bare privilege failure is only interesting when we are *not* elevated;
    # otherwise the cause is something else and the generic error is more honest.
    return "privilege" in lowered and not is_admin()


def elevation_refusal(target: str | None = None) -> dict[str, object]:
    """Structured 'this needs admin' refusal, instead of a cryptic failure."""
    if os.name == "nt":
        hint = ("Run the agent from an elevated terminal (right-click > "
                "'Run as administrator'), or change the setting manually.")
    else:
        hint = ("Re-run with sudo, or add your user to the relevant group "
                "(e.g. 'video' for brightness on many laptops).")
    what = f"Changing {target}" if target else "That action"
    return {
        "code": "needs_elevation",
        "retryable": False,
        "target": target,
        "admin": is_admin(),
        "user_hint": hint,
        "message": f"{what} was refused: this needs administrator rights.",
    }


# --------------------------------------------------------------------------- panic
class PanicActive(Exception):
    """Raised while the panic switch is engaged: nothing may run."""


_PANIC = threading.Event()
_PANIC_REASON = {"reason": ""}

#: Tools that change something and are therefore blocked while panicking. Read-only
#: inspection stays available, which is what you want when you are investigating.
DESTRUCTIVE_TOOLS = frozenset({
    "hardware_control", "hardware_undo", "app_lifecycle", "workspace_fs",
    "power_session", "clipboard", "open_target", "notify", "media_control",
    "remember", "forget", "save_profile", "focus_mode", "organize",
})


def panic_active() -> bool:
    return _PANIC.is_set()


def panic_reason() -> str:
    return _PANIC_REASON["reason"]


def set_panic(active: bool, reason: str = "operator panic stop") -> None:
    """Engage or release the panic switch (Tier 1 'panic stop')."""
    if active:
        _PANIC_REASON["reason"] = reason
        _PANIC.set()
    else:
        _PANIC_REASON["reason"] = ""
        _PANIC.clear()


def assert_not_panicking(tool: str | None = None) -> None:
    """Raise :class:`PanicActive` when *tool* may not run right now."""
    if not panic_active():
        return
    if tool is None or tool in DESTRUCTIVE_TOOLS:
        raise PanicActive(
            f"The panic switch is engaged ({panic_reason() or 'manual'}); "
            f"'{tool or 'this action'}' was blocked."
        )


# --------------------------------------------------------------------------- battery
def battery_state() -> dict[str, object]:
    """Battery percentage and plug state, or ``available: False``."""
    try:
        import psutil

        battery = psutil.sensors_battery()
    except Exception:                                     # no sensor / no psutil
        return {"available": False}
    if battery is None:
        return {"available": False}
    return {
        "available": True,
        "percent": round(float(battery.percent), 1),
        "plugged_in": bool(battery.power_plugged),
    }


#: Actions that are worth a full battery; everything else is cheap or read-only.
HEAVY_TOOLS = frozenset({"organize", "screenshot", "search_documents",
                         "system_inventory", "app_lifecycle", "power_session"})


def battery_guard(tool: str | None = None) -> dict[str, object] | None:
    """Return a refusal payload when the battery is too low for this action."""
    if not config.BATTERY_GUARD_ENABLED:
        return None
    if tool is not None and tool not in HEAVY_TOOLS:
        return None
    state = battery_state()
    if not state.get("available") or state.get("plugged_in"):
        return None
    percent = float(state.get("percent") or 100.0)   # type: ignore[arg-type]
    if percent >= config.BATTERY_GUARD_PERCENT:
        return None
    return {
        "code": "battery_low",
        "retryable": True,
        "user_hint": ("Plug the machine in, or set AGENT_BATTERY_GUARD_ON=0 to "
                      "disable this guard."),
        "battery_percent": percent,
        "threshold": config.BATTERY_GUARD_PERCENT,
        "message": (f"Battery is at {percent:.0f}% (guard: "
                    f"{config.BATTERY_GUARD_PERCENT}%); '{tool}' was not run."),
    }


# --------------------------------------------------------------------------- reset
def reset_panic() -> None:
    """Test helper: release the panic switch."""
    set_panic(False)
