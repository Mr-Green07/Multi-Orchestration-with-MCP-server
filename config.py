"""config.py
=========
Single source of truth for the whole project.

Everything that used to be scattered across modules now lives here: the one
workspace jail root, the model path and decode settings, the audit location, the
policy tables (protected processes, launch allowlist), rate limits and every
resource cap.

Nothing in this module imports the rest of the project, so it is safe to import
from anywhere (server, tools, agent, tests) without circular imports.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- paths
BASE_DIR = Path(__file__).resolve().parent


def _path_env(name: str, default: Path) -> Path:
    """Read a path from the environment, expanding ``~`` and resolving it."""
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default.resolve()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- logging
LOG_LEVEL = os.environ.get("AGENT_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    stream=sys.stderr,                      # never pollute the MCP stdio transport
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)

# --------------------------------------------------------------------------- jail
#: The single workspace jail. Both the MCP tool and the legacy ``security`` module
#: resolve paths against this, so there is exactly one boundary to reason about.
WORKSPACE_JAIL_ROOT = _path_env("WORKSPACE_JAIL_ROOT", BASE_DIR / "workspace")
DATABASE_DIR = _path_env("AGENT_DATABASE_DIR", BASE_DIR / "database")
LOG_DIR = _path_env("AGENT_LOG_DIR", BASE_DIR / "logs")
AUDIT_DIR = _path_env("AGENT_AUDIT_DIR", LOG_DIR)
MEMORY_DB_PATH = _path_env("AGENT_MEMORY_DB", DATABASE_DIR / "agent_memory.db")


def ensure_dirs() -> None:
    """Create the runtime directories. Called lazily, never at import time."""
    for directory in (WORKSPACE_JAIL_ROOT, DATABASE_DIR, AUDIT_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:                     # read-only install: tools report it
            pass


# --------------------------------------------------------------------------- model
MODEL_PATH = _path_env(
    "AGENT_MODEL_PATH",
    BASE_DIR / "models" / "Qwen3.5-4BQ" / "model.gguf",
)
LLM_N_CTX = _int_env("AGENT_N_CTX", 2048)
LLM_N_BATCH = _int_env("AGENT_N_BATCH", 256)
LLM_GPU_LAYERS = _int_env("AGENT_GPU_LAYERS", -1)
LLM_TEMPERATURE = float(os.environ.get("AGENT_TEMPERATURE", "0.0"))
LLM_MAX_TOKENS = _int_env("AGENT_MAX_TOKENS", 384)

# --------------------------------------------------------------------------- runtime
#: When true, no host-changing action is executed; the resolved call is reported.
DRY_RUN = _bool_env("AGENT_DRY_RUN", False)
AUDIT_ENABLED = not _bool_env("AGENT_AUDIT_DISABLED", False)

MAX_STEPS = _int_env("AGENT_MAX_STEPS", 4)          # reasoning steps per request
MAX_REPAIRS = _int_env("AGENT_MAX_REPAIRS", 1)      # bounded self-repair attempts
MAX_TOOL_SECONDS = float(os.environ.get("AGENT_TOOL_TIMEOUT", "10"))
MAX_OUTPUT_CHARS = 4000
MAX_FILE_BYTES = 1_000_000
MAX_READ_CHARS = 4000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_FILES = 2000
MAX_SEARCH_MATCHES = 50
MAX_TREE_DEPTH = 4
CONFIRMATION_TTL_SECONDS = _int_env("AGENT_CONFIRM_TTL", 120)

# --------------------------------------------------------------------------- policy
#: Processes whose termination would end the user's session or destabilise the
#: machine. Checked before a token is even issued, so policy cannot be argued away.
PROTECTED_PROCESSES = frozenset({
    "system", "system idle process", "registry", "memory compression",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "lsaiso.exe", "svchost.exe", "explorer.exe", "dwm.exe",
    "fontdrvhost.exe", "sihost.exe", "taskhostw.exe", "ctfmon.exe",
    "audiodg.exe", "spoolsv.exe", "msmpeng.exe", "securityhealthservice.exe",
    "init", "systemd", "kthreadd", "kworker", "launchd", "kernel_task",
    "windowserver", "loginwindow", "finder", "xorg", "xwayland", "gnome-shell",
    "plasmashell", "kwin_x11", "kwin_wayland", "wayland", "dbus-daemon",
    "pipewire", "pulseaudio", "systemd-journald", "sshd",
})

#: Applications the agent may launch. Each entry is an argv list per platform, so
#: no shell string is ever constructed and no model-supplied text is executed.
ALLOWED_APPS: dict[str, dict[str, list[str]]] = {
    "vscode": {
        "win32": ["code.cmd"],
        "darwin": ["open", "-a", "Visual Studio Code"],
        "linux": ["code"],
    },
    "browser": {
        "win32": ["cmd", "/c", "start", "", "chrome"],
        "darwin": ["open", "-a", "Google Chrome"],
        "linux": ["xdg-open", "https://www.google.com"],
    },
    "terminal": {
        "win32": ["wt.exe"],
        "darwin": ["open", "-a", "Terminal"],
        "linux": ["x-terminal-emulator"],
    },
    "calculator": {
        "win32": ["calc.exe"],
        "darwin": ["open", "-a", "Calculator"],
        "linux": ["gnome-calculator"],
    },
    "explorer": {
        "win32": ["explorer.exe"],
        "darwin": ["open", "."],
        "linux": ["xdg-open", "."],
    },
    "notepad": {
        "win32": ["notepad.exe"],
        "darwin": ["open", "-a", "TextEdit"],
        "linux": ["gedit"],
    },
}

#: Conversation memory: recent turns kept verbatim, by count and by characters.
MEMORY_MAX_TURNS = _int_env("AGENT_MEMORY_TURNS", 4)
MEMORY_MAX_CHARS = _int_env("AGENT_MEMORY_CHARS", 2400)

#: Deterministic shortcut classifier (obvious read-only requests skip inference).
USE_CLASSIFIER = _bool_env("AGENT_CLASSIFIER", True)

#: Battery-aware behaviour: below this charge (and not plugged in) the agent
#: refuses heavy actions instead of draining the machine.
BATTERY_GUARD_PERCENT = _int_env("AGENT_BATTERY_GUARD", 20)
BATTERY_GUARD_ENABLED = _bool_env("AGENT_BATTERY_GUARD_ON", True)

#: Read-only inventory (services, startup items, installed apps, event-log rows)
#: is capped so a probing question can never produce a megabyte of payload.
MAX_INVENTORY_ROWS = _int_env("AGENT_MAX_INVENTORY_ROWS", 60)

#: Tool contract version - bumped when a tool's arguments change, so prompt
#: caches and saved profiles can be invalidated deliberately.
TOOL_SCHEMA_VERSION = "1.0.0"

#: Ask before launching an allowlisted application. Off by default because launch
#: is already restricted to four fixed argv lists; turn on for a stricter posture.
REQUIRE_LAUNCH_APPROVAL = _bool_env("AGENT_APPROVE_LAUNCH", False)

#: Extra directories the agent may *read* (never write) when the user opts in.
#: Colon-separated on POSIX, semicolon-separated on Windows.
def _path_list(name: str) -> tuple[Path, ...]:
    raw = os.environ.get(name, "")
    if not raw:
        return ()
    separator = ";" if os.name == "nt" else ":"
    return tuple(Path(part).expanduser().resolve()
                 for part in raw.split(separator) if part.strip())


READ_ONLY_ROOTS = _path_list("AGENT_READ_ONLY_ROOTS")

#: URL schemes the ``open_target`` tool will hand to the OS.
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto"})

#: Absolute upper bounds for destructive actions, enforced in the server.
MAX_POWER_ACTIONS_PER_HOUR = _int_env("AGENT_MAX_POWER_PER_HOUR", 6)
MIN_POWER_GAP_SECONDS = float(os.environ.get("AGENT_MIN_POWER_GAP", "30"))


@dataclass(frozen=True)
class RateLimit:
    """Sliding-window budget for one class of actions."""

    name: str
    max_events: int
    window_seconds: float
    min_gap_seconds: float = 0.0


POWER_RATE_LIMIT = RateLimit(
    name="power",
    max_events=MAX_POWER_ACTIONS_PER_HOUR,
    window_seconds=3600.0,
    min_gap_seconds=MIN_POWER_GAP_SECONDS,
)
TERMINATION_RATE_LIMIT = RateLimit(
    name="termination",
    max_events=_int_env("AGENT_MAX_KILLS_PER_HOUR", 10),
    window_seconds=3600.0,
    min_gap_seconds=0.0,
)
