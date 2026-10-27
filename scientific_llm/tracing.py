"""scientific_llm/tracing.py
==========================
Agent tracing and structured handoffs (roadmap item 16).

A multi-agent system is only debuggable if you can answer three questions after the
fact: *which agent did what, in which order, and what exactly did it hand over?*

So every step is a :class:`TraceEvent` and every agent-to-agent transfer is a
:class:`Handoff` with a typed payload. The trace serialises to JSON (for the API)
and to JSONL (for the benchmark run), so a failing answer can be replayed offline.

This module has no dependencies and no I/O until you ask for it.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class TraceEvent:
    """One unit of work performed by one agent."""

    agent: str
    action: str
    started_at: str = field(default_factory=_now_iso)
    latency_ms: float = 0.0
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent, "action": self.action,
            "started_at": self.started_at, "latency_ms": round(self.latency_ms, 2),
            "detail": self.detail, "payload": self.payload,
        }


@dataclass
class Handoff:
    """A structured transfer of work (and data) between two agents."""

    from_agent: str
    to_agent: str
    reason: str
    payload_summary: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=_now_iso)

    def as_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_agent, "to": self.to_agent, "reason": self.reason,
            "payload": self.payload_summary, "at": self.at,
        }


class Trace:
    """An ordered, serialisable record of one question's journey."""

    def __init__(self, question: str, system: str = "multi_agent") -> None:
        self.trace_id = uuid.uuid4().hex[:12]
        self.question = question
        self.system = system
        self.created_at = _now_iso()
        self.events: list[TraceEvent] = []
        self.handoffs: list[Handoff] = []
        self.metadata: dict[str, Any] = {}

    # ------------------------------------------------------------------ recording
    def add(self, agent: str, action: str, *, detail: str = "",
            latency_ms: float = 0.0, **payload: Any) -> TraceEvent:
        event = TraceEvent(agent=agent, action=action, detail=detail,
                           latency_ms=latency_ms, payload=payload)
        self.events.append(event)
        return event

    def handoff(self, from_agent: str, to_agent: str, reason: str,
                **payload_summary: Any) -> Handoff:
        transfer = Handoff(from_agent=from_agent, to_agent=to_agent, reason=reason,
                           payload_summary=payload_summary)
        self.handoffs.append(transfer)
        return transfer

    def span(self, agent: str, action: str) -> _Span:
        """Context manager that times a block and records it on exit."""
        return _Span(self, agent, action)

    # ------------------------------------------------------------------ reading
    def agents(self) -> list[str]:
        """Agents in first-appearance order (a readable call chain)."""
        seen: list[str] = []
        for event in self.events:
            if event.agent not in seen:
                seen.append(event.agent)
        return seen

    def total_ms(self) -> float:
        return round(sum(event.latency_ms for event in self.events), 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id, "question": self.question,
            "system": self.system, "created_at": self.created_at,
            "agents": self.agents(), "total_ms": self.total_ms(),
            "events": [event.as_dict() for event in self.events],
            "handoffs": [handoff.as_dict() for handoff in self.handoffs],
            "metadata": self.metadata,
        }

    def summary_lines(self) -> list[str]:
        lines = [f"trace {self.trace_id} ({self.system}) - {self.total_ms():.1f} ms"]
        for event in self.events:
            suffix = f" - {event.detail}" if event.detail else ""
            lines.append(f"  {event.agent:<22} {event.action:<18} "
                         f"{event.latency_ms:7.1f} ms{suffix}")
        for handoff in self.handoffs:
            lines.append(f"  handoff {handoff.from_agent} -> {handoff.to_agent}"
                         f" ({handoff.reason})")
        return lines

    def write_jsonl(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.as_dict(), ensure_ascii=False) + "\n")
        return target


class _Span:
    """Times a block of work and records it, even if the block raises."""

    def __init__(self, trace: Trace, agent: str, action: str) -> None:
        self.trace = trace
        self.agent = agent
        self.action = action
        self.detail = ""
        self.payload: dict[str, Any] = {}
        self._started = 0.0

    def __enter__(self) -> _Span:
        self._started = time.perf_counter()
        return self

    def note(self, detail: str, **payload: Any) -> None:
        self.detail = detail
        self.payload.update(payload)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        elapsed = (time.perf_counter() - self._started) * 1000.0
        detail = self.detail
        if exc is not None:
            detail = f"failed: {type(exc).__name__}: {exc}"
            self.payload["error"] = str(exc)[:300]
        self.trace.add(self.agent, self.action, detail=detail,
                       latency_ms=elapsed, **self.payload)
        # Returning None (not True) means an exception is never swallowed.
