"""The planner loop, driven by scripted model replies and a fake MCP client.

These tests describe the contract that matters: bounded steps, bounded repairs,
clarification instead of guessing, and no destructive action without approval.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

import config
from agent.llm import ScriptedLLM
from agent.orchestrator import Orchestrator, parse_decision


# --------------------------------------------------------------------------- fakes
class FakeTool:
    def __init__(self, name: str, schema: dict[str, Any] | None = None,
                 description: str = "a tool"):
        self.name = name
        self.description = description
        self.input_schema = schema or {"type": "object", "properties": {}}


class CallResult:
    def __init__(self, data: dict[str, Any]):
        self.data = data


class FakeClient:
    """Stands in for fastmcp.Client; queues one response per tool invocation."""

    def __init__(self, tools: list[FakeTool], responses: dict[str, list[dict[str, Any]]]):
        self.tools = tools
        self.responses = {name: list(queue) for name, queue in responses.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        self.calls.append((name, arguments))
        queue = self.responses.get(name, [])
        if queue:
            return CallResult(queue.pop(0))
        return CallResult({"status": "success", "summary": f"{name} ok", "payload": {}})


def build(responses: list[str], tools=None, tool_responses=None, **kwargs):
    tools = tools if tools is not None else [FakeTool("system_telemetry",
                               {"type": "object", "properties": {"metric": {"type": "string"}}}),
                      FakeTool("power_session",
                               {"type": "object", "properties": {"action": {"type": "string"}}})]
    client = FakeClient(tools, tool_responses or {})
    llm = ScriptedLLM(responses)
    orch = Orchestrator(llm=llm, client_factory=lambda: client, **kwargs)
    return orch, client, llm


def tool_call(name: str, **arguments) -> str:
    return json.dumps({"action": "tool", "tool": name, "arguments": arguments})


def final(text: str) -> str:
    return json.dumps({"action": "final", "answer": text})


# --------------------------------------------------------------------------- parsing
def test_parse_tool_decision():
    decision, error = parse_decision(tool_call("system_telemetry", metric="cpu"),
                                     ["system_telemetry"])
    assert error == ""
    assert decision["action"] == "tool"
    assert decision["arguments"] == {"metric": "cpu"}


def test_parse_rejects_unknown_tool_and_missing_fields():
    decision, error = parse_decision(tool_call("rm_rf"), ["system_telemetry"])
    assert decision is None and "unknown tool" in error

    decision, error = parse_decision('{"action":"final"}', ["system_telemetry"])
    assert decision is None and "answer" in error

    decision, error = parse_decision('{"action":"tool","tool":"system_telemetry",'
                                     '"arguments":"oops"}', ["system_telemetry"])
    assert decision is None and "JSON object" in error


def test_parse_accepts_fenced_output_with_prose():
    raw = "Sure, here you go:\n```json\n" + final("done") + "\n```"
    decision, error = parse_decision(raw, [])
    assert error == "" and decision["answer"] == "done"


# --------------------------------------------------------------------------- loop
@pytest.mark.asyncio
async def test_single_tool_then_answer():
    orch, client, _ = build(
        [tool_call("system_telemetry", metric="memory"), final("Your RAM is fine.")],
        tool_responses={"system_telemetry": [
            {"status": "success", "summary": "memory telemetry retrieved",
             "payload": {"usage_percent": 41}}]},
    )
    result = await orch.run("how much memory am I using?")

    assert result.status == "ok"
    assert result.answer == "Your RAM is fine."
    assert result.steps == 1
    assert result.tool_calls[0].tool == "system_telemetry"
    assert client.calls == [("system_telemetry", {"metric": "memory"})]


@pytest.mark.asyncio
async def test_multi_step_loop_feeds_observations_back():
    orch, client, llm = build([
        tool_call("system_telemetry", metric="cpu"),
        tool_call("system_telemetry", metric="memory"),
        final("CPU and memory both normal."),
    ])

    result = await orch.run("is anything wrong?")

    assert result.steps == 2
    assert result.status == "ok"
    # the second prompt must contain the first observation
    second_call_messages = llm.calls[1]
    assert any("TOOL RESULT for system_telemetry" in m["content"] for m in second_call_messages)


@pytest.mark.asyncio
async def test_step_limit_is_enforced():
    responses = [tool_call("system_telemetry", metric="cpu")] * 10
    orch, client, _ = build(responses, max_steps=3)

    result = await orch.run("loop forever")

    assert result.steps == 3
    assert result.error == "step limit reached"
    assert "maximum number of steps" in result.answer
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_malformed_output_is_repaired_once():
    orch, _client, llm = build(["not json at all", final("recovered")])

    result = await orch.run("hello")

    assert result.status == "ok"
    assert result.answer == "recovered"
    assert any("could not be used" in m["content"] for m in llm.calls[1])


@pytest.mark.asyncio
async def test_repeated_malformed_output_stops_with_an_error():
    orch, _client, _ = build(["nope", "still nope", "nope again"], max_repairs=1)

    result = await orch.run("hello")

    assert result.status == "error"
    assert "unusable output" in result.answer


@pytest.mark.asyncio
async def test_ambiguous_request_asks_the_user():
    orch, client, _ = build([json.dumps({"action": "ask_user",
                                         "question": "Which volume, speaker or headset?"})])

    result = await orch.run("make it louder")

    assert result.status == "needs_input"
    assert result.question == "Which volume, speaker or headset?"
    assert client.calls == []


@pytest.mark.asyncio
async def test_tool_error_is_observed_not_fatal():
    orch, _client, llm = build(
        [tool_call("system_telemetry", metric="cpu"), final("That metric failed.")],
        tool_responses={"system_telemetry": [
            {"status": "error", "summary": "boom", "payload": {"code": "x"}}]},
    )
    result = await orch.run("cpu please")
    assert result.status == "ok"
    assert "boom" in llm.calls[1][-1]["content"]


# --------------------------------------------------------------------------- approvals
@pytest.mark.asyncio
async def test_approval_grants_the_token_and_executes():
    seen = {}

    def approve(info):
        seen.update(info)
        return True

    orch, client, _ = build(
        [tool_call("power_session", action="shutdown"), final("Shutting down.")],
        tool_responses={"power_session": [
            {"status": "requires_confirmation", "summary": "needs confirmation",
             "confirmation_token": "tok-1", "payload": {"warning": "everything closes"}},
            {"status": "success", "summary": "shutdown initiated"},
        ]},
        approve=approve,
    )

    result = await orch.run("shut the machine down")

    assert result.status == "ok"
    assert seen["tool"] == "power_session"
    assert seen["warning"] == "everything closes"
    # the retry must carry the token
    assert client.calls[1] == ("power_session",
                              {"action": "shutdown", "confirmation_token": "tok-1"})
    assert result.tool_calls[-1].status == "success"


@pytest.mark.asyncio
async def test_declined_approval_cancels_and_executes_nothing():
    orch, client, _ = build(
        [tool_call("power_session", action="shutdown")],
        tool_responses={"power_session": [
            {"status": "requires_confirmation", "summary": "needs confirmation",
             "confirmation_token": "tok-1", "payload": {}}]},
        approve=lambda _info: False,
    )

    result = await orch.run("shut the machine down")

    assert result.status == "cancelled"
    assert len(client.calls) == 1          # no execution call was made
    assert "cancelled by the user" in result.answer


@pytest.mark.asyncio
async def test_without_an_approver_the_token_is_never_used():
    orch, client, _ = build(
        [tool_call("power_session", action="shutdown"), final("I need your approval.")],
        tool_responses={"power_session": [
            {"status": "requires_confirmation", "summary": "needs confirmation",
             "confirmation_token": "tok-1", "payload": {}}]},
    )
    result = await orch.run("shut it down")
    assert result.status == "ok"
    assert len(client.calls) == 1
    assert result.tool_calls[0].status == "requires_confirmation"


# --------------------------------------------------------------------------- modes
@pytest.mark.asyncio
async def test_dry_run_flag_is_applied_and_restored(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    orch, _client, _ = build([final("done")], dry_run=True)

    result = await orch.run("do something")

    assert result.dry_run is True
    assert config.DRY_RUN is False           # restored after the request


@pytest.mark.asyncio
async def test_no_tools_is_an_error():
    orch, _client, _ = build([final("hi")], tools=[])
    result = await orch.run("hello")
    assert result.status == "error"
    assert "no tools" in result.answer.lower()


@pytest.mark.asyncio
async def test_profile_replay_runs_each_step():
    orch, client, _ = build(
        [final("unused")],
        tool_responses={"get_profile": [{
            "status": "success",
            "summary": "profile",
            "payload": {"steps": [
                {"tool": "system_telemetry", "arguments": {"metric": "cpu"}},
                {"tool": "system_telemetry", "arguments": {"metric": "memory"}},
            ]},
        }]},
    )
    result = await orch.run_profile("work")
    assert result.status == "ok"
    assert result.steps == 2
    assert [c["metric"] for _name, c in client.calls[1:]] == ["cpu", "memory"]
