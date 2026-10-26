"""Integration: the two-phase confirmation flow through the real MCP server,
and the backwards-compatible orchestrator shim.
"""
from __future__ import annotations

import json

import pytest
from fastmcp import Client

from agent.llm import ScriptedLLM
from mcp_server.server import mcp
from orchestrator.agent import SystemAgentOrchestrator


def _flag(annotations, name: str):
    """Read an MCP annotation under either naming convention (SDK v1/v2)."""
    for attribute in (f"{name}_hint", f"{name}Hint"):
        if hasattr(annotations, attribute):
            return getattr(annotations, attribute)
    return None


@pytest.mark.asyncio
async def test_two_phase_confirmation_token_flow():
    """Token first, then a rejected invalid token, then no execution at all."""
    async with Client(mcp) as client:
        first = await client.call_tool("power_session", {"action": "shutdown"})
        assert first.data["status"] == "requires_confirmation"
        assert first.data["confirmation_token"]

        second = await client.call_tool(
            "power_session",
            {"action": "shutdown", "confirmation_token": "invalid_token_123"},
        )
        assert second.data["status"] == "error"
        assert "invalid" in second.data["summary"].lower()


@pytest.mark.asyncio
async def test_tools_are_discoverable_and_annotated():
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    for expected in ("system_telemetry", "machine_health", "hardware_control",
                     "app_lifecycle", "workspace_fs", "power_session",
                     "search_documents", "clipboard"):
        assert expected in tools, f"{expected} is not published"

    telemetry_annotations = tools["system_telemetry"].annotations
    assert telemetry_annotations is not None
    assert _flag(telemetry_annotations, "read_only") is True

    power_annotations = tools["power_session"].annotations
    assert power_annotations is not None
    assert _flag(power_annotations, "destructive") is True


@pytest.mark.asyncio
async def test_orchestrator_shim_returns_the_legacy_shape():
    responses = [
        json.dumps({"action": "tool", "tool": "system_telemetry",
                    "arguments": {"metric": "memory"}}),
        json.dumps({"action": "final", "answer": "Memory is fine."}),
    ]
    agent = SystemAgentOrchestrator(llm=ScriptedLLM(responses))

    result = await agent.execute_query("how is memory?")

    assert result["status"] == "success"
    assert result["answer"] == "Memory is fine."
    assert result["payload"]["tool_calls"][0]["tool"] == "system_telemetry"


@pytest.mark.asyncio
async def test_orchestrator_against_the_real_server_answers_in_language():
    responses = [
        json.dumps({"action": "tool", "tool": "machine_health", "arguments": {}}),
        json.dumps({"action": "final", "answer": "Everything looks healthy."}),
    ]
    agent = SystemAgentOrchestrator(llm=ScriptedLLM(responses))

    result = await agent.execute_query("is my machine okay?")

    assert result["status"] == "success"
    assert result["payload"]["steps"] == 1
    assert result["payload"]["tool_calls"][0]["status"] == "success"
