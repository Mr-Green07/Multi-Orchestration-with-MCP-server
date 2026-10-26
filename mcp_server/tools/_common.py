"""mcp_server/tools/_common.py
===========================
Helpers shared by every tool: response construction (which also writes the audit
record), jail resolution, text-file guards and dry-run simulation.

Keeping ``respond`` in one place is what makes the audit trail complete: a tool
cannot return a result that is not recorded.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

import config
from mcp_server import audit, policy
from mcp_server.schemas import SystemToolResponse

TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json",
    ".jsonl", ".yaml", ".yml", ".ini", ".toml", ".cfg", ".conf", ".xml",
    ".html", ".htm", ".css", ".js", ".ts", ".py", ".ps1", ".bat", ".sh",
    ".c", ".h", ".cpp", ".hpp", ".java", ".sql", ".env", ".gitignore",
})
SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv",
                       ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist",
                       "build", ".idea", ".vscode"})


# --------------------------------------------------------------------------- responses
def respond(
    *,
    tool: str,
    action: str,
    status: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    arguments: dict[str, Any] | None = None,
    confirmation_token: str | None = None,
    applied: bool | None = None,
    previous: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    approval: str | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    """Build a response *and* write its audit record."""
    correlation_id = correlation_id or audit.current_correlation()
    response = SystemToolResponse(
        status=status,                     # type: ignore[arg-type]
        metric_or_action=action,
        summary=summary,
        payload=payload or {},
        confirmation_token=confirmation_token,
        correlation_id=correlation_id,
        applied=applied,
        previous=previous,
    )
    audit.tool_event(
        tool=tool,
        status=status,
        summary=summary,
        arguments=arguments,
        payload=payload or {},
        correlation_id=correlation_id,
        approval=approval,
        duration_ms=duration_ms,
    )
    return response.model_dump()


def simulate(
    *,
    tool: str,
    action: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    arguments: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Return a ``dry_run`` response describing what would have happened."""
    body = dict(payload or {})
    body["would_execute"] = True
    return respond(
        tool=tool,
        action=action,
        status="dry_run",
        summary=f"[dry run] {summary}",
        payload=body,
        arguments=arguments,
        correlation_id=correlation_id,
        applied=False,
    )


# --------------------------------------------------------------------------- jail
class JailViolation(Exception):
    """Raised when a requested path escapes the workspace jail."""


def jail_root() -> Path:
    root = Path(config.WORKSPACE_JAIL_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def resolve_in_jail(relative_path: str | None) -> Path:
    """Resolve *relative_path* inside the jail or raise :class:`JailViolation`."""
    raw = (relative_path or "").strip()
    if not raw or raw in {".", "./"}:
        return jail_root()

    lowered = raw.lower()
    if raw.startswith(("/", "\\")) or lowered.startswith(("file:", "http:", "https:")):
        raise JailViolation(f"Absolute paths are not allowed inside the jail: '{raw}'.")
    if PurePosixPath(raw.replace("\\", "/")).is_absolute():
        raise JailViolation(f"Absolute paths are not allowed inside the jail: '{raw}'.")
    if len(raw) > 1 and raw[1] == ":":
        raise JailViolation(f"Drive-qualified paths are not allowed: '{raw}'.")
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise JailViolation("UNC network paths are not allowed.")

    root = jail_root()
    target = (root / raw).resolve()
    if target != root and not target.is_relative_to(root):
        raise JailViolation(
            "Security violation: Path traversal outside workspace jail is forbidden."
        )
    return target


# --------------------------------------------------------------- read-only scopes
SCOPE_PREFIX = "@"
SCOPE_INDEX = "@scopes"


def read_only_scopes() -> dict[str, Path]:
    """Named, opt-in, read-only directories outside the jail.

    Configured with ``AGENT_READ_ONLY_ROOTS`` (``:``-separated on POSIX). The scope
    name is the directory's own name, e.g. ``/home/me/Downloads`` -> ``@Downloads``.
    Nothing here is ever writable: writes stay inside the jail.
    """
    scopes: dict[str, Path] = {}
    for root in getattr(config, "READ_ONLY_ROOTS", ()) or ():
        path = Path(root).expanduser()
        if not path.is_dir():
            continue
        name = path.name or "root"
        candidate, counter = name, 2
        while candidate in scopes:                       # keep names unique
            candidate = f"{name}{counter}"
            counter += 1
        scopes[candidate] = path.resolve()
    return scopes


def resolve_read_only(relative_path: str) -> Path:
    """Resolve ``@scope/sub/path`` inside a configured read-only root."""
    scopes = read_only_scopes()
    if not scopes:
        raise JailViolation(
            "No read-only scopes are configured. Set AGENT_READ_ONLY_ROOTS to a "
            "list of directories (colon-separated) to enable reading outside the jail."
        )
    raw = (relative_path or "").strip()
    body = raw[len(SCOPE_PREFIX):]
    name, _, rest = body.partition("/")
    if name not in scopes:
        raise JailViolation(
            f"Unknown scope '@{name}'. Configured scopes: "
            f"{', '.join('@' + key for key in scopes)}."
        )
    root = scopes[name]
    target = (root / rest).resolve() if rest else root
    if target != root and not target.is_relative_to(root):
        raise JailViolation(
            "Security violation: path traversal outside the read-only scope is forbidden."
        )
    return target


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name.lower() in {
        "makefile", "dockerfile", "license", "readme",
    }


def read_text_capped(path: Path, limit: int | None = None) -> tuple[str, bool]:
    """Read a text file with a hard byte cap; returns (text, truncated)."""
    limit = config.MAX_READ_CHARS if limit is None else limit
    size = path.stat().st_size
    if size > config.MAX_FILE_BYTES:
        raise ValueError(
            f"File is too large ({size} bytes; limit {config.MAX_FILE_BYTES})."
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > limit
    return (text[:limit], truncated)


def iter_jail_files(root: Path, limit: int = config.MAX_SEARCH_FILES):
    """Yield text files under *root*, bounded in count and skipping vendor dirs."""
    produced = 0
    for path in root.rglob("*"):
        if produced >= limit:
            return
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or not is_text_file(path):
            continue
        produced += 1
        yield path


def matches_glob(name: str, pattern: str | None) -> bool:
    return True if not pattern else fnmatch.fnmatch(name, pattern)


def unsupported(tool: str, action: str, detail: str,
                hint: str | None = None) -> dict[str, Any]:
    """Standard response when a capability is missing on this host."""
    payload = {"code": "unsupported", "detail": detail, "platform": policy.host_platform()}
    if hint:
        payload["hint"] = hint
    return respond(
        tool=tool, action=action, status="unsupported",
        summary=f"{detail} (unsupported on this host)",
        payload=payload,
    )
