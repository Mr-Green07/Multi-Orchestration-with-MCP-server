"""orchestrator/agent.py
=====================
Compatibility shim.

The real planning loop now lives in :mod:`agent.orchestrator`. This module keeps
the original public name (``SystemAgentOrchestrator.execute_query``) for scripts
that still import it, and it no longer imports ``llama_cpp`` at module scope - so
importing it works on a machine without the model runtime.
"""
from __future__ import annotations

import asyncio
from typing import Any

from agent.llm import LLM, LocalLLM
from agent.orchestrator import Orchestrator

MODEL_PATH = None          # retained for older callers; see agent.llm.config


class SystemAgentOrchestrator:
    """Backwards-compatible wrapper around :class:`agent.orchestrator.Orchestrator`."""

    def __init__(self, llm: LLM | None = None, approve=None, dry_run: bool | None = None):
        self.llm = llm or LocalLLM()
        self.approve = approve
        self.dry_run = dry_run

    def _build(self) -> Orchestrator:
        return Orchestrator(self.llm, approve=self.approve, dry_run=self.dry_run)

    async def execute_query(self, user_prompt: str) -> dict[str, Any]:
        """Run one request and return the flat dictionary older callers expect."""
        result = await self._build().run(user_prompt)
        return {
            "status": "success" if result.status == "ok" else result.status,
            "summary": result.answer,
            "answer": result.answer,
            "metric_or_action": "agent_request",
            "payload": {
                "steps": result.steps,
                "tool_calls": [call.as_dict() for call in result.tool_calls],
                "correlation_id": result.correlation_id,
                "dry_run": result.dry_run,
            },
            "correlation_id": result.correlation_id,
        }

    def execute_query_sync(self, user_prompt: str) -> dict[str, Any]:
        return asyncio.run(self.execute_query(user_prompt))
