"""mcp_server/audit.py
===================
Append-only JSONL audit trail.

Every request, decision, tool call, argument set, result and approval decision is
written as one JSON object per line, tagged with a correlation id so a whole user
turn can be reconstructed. The writer is bounded and fail-safe: a full disk or a
read-only install must never take the agent down, so failures are logged and
swallowed.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_VALUE_CHARS = 500

#: Correlation id for the request currently being served. Set by the orchestrator
#: (and by tests); tool responses inherit it, so one user turn is one thread of
#: audit records even though the tools never see the id explicitly.
_CORRELATION: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_correlation", default=None)


def current_correlation() -> str | None:
    return _CORRELATION.get()


def set_correlation(correlation_id: str | None):
    return _CORRELATION.set(correlation_id)


def reset_correlation(token) -> None:
    _CORRELATION.reset(token)


def new_correlation_id() -> str:
    """Short, sortable-enough id used to group one user request's events."""
    return f"{int(time.time()):x}-{uuid.uuid4().hex[:6]}"


def _shrink(value: Any) -> Any:
    """Keep audit lines small without losing the shape of the record."""
    if isinstance(value, dict):
        return {k: _shrink(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_shrink(v) for v in value[:20]]
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return value[:_MAX_VALUE_CHARS] + f"...[{len(value)} chars]"
    return value


def current_log_path(when: float | None = None) -> Path:
    stamp = time.strftime("%Y-%m-%d", time.localtime(when))
    return Path(config.AUDIT_DIR) / f"audit-{stamp}.jsonl"


def record(event: str, **fields: Any) -> dict[str, Any]:
    """Append one audit record and return it (useful in tests).

    Never raises. Set ``AGENT_AUDIT_DISABLED=1`` to make it a no-op.
    """
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        "pid": os.getpid(),
        **{k: _shrink(v) for k, v in fields.items()},
    }
    if not config.AUDIT_ENABLED:
        return entry

    try:
        path = current_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:            # auditing must never break the agent
        logger.warning("audit write failed: %s", exc)
    return entry


def tool_event(
    *,
    tool: str,
    status: str,
    summary: str,
    arguments: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    duration_ms: float | None = None,
    approval: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for the shape every tool call writes."""
    correlation_id = correlation_id or current_correlation()
    return record(
        "tool_call",
        tool=tool,
        status=status,
        summary=summary,
        arguments=arguments or {},
        payload=payload or {},
        correlation_id=correlation_id,
        duration_ms=round(duration_ms, 3) if duration_ms is not None else None,
        approval=approval,
    )


def tail(limit: int = 20) -> list[dict[str, Any]]:
    """Return the last *limit* records from the current day's log."""
    path = current_log_path()
    if not path.exists():
        return []
    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                lines.append(line)
                if len(lines) > limit:
                    lines.pop(0)
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
