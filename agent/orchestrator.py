"""agent/orchestrator.py
=====================
The planning loop.

One user turn becomes: build a prompt from the live tool list -> ask the model for
one JSON decision -> validate it -> execute it through MCP -> feed the observation
back -> repeat, bounded. Three properties are deliberate:

* **bounded** - ``MAX_STEPS`` reasoning steps and ``MAX_REPAIRS`` malformed-output
  retries are counters in this file, not requests in a prompt;
* **observable** - every step emits an event (for the CLI) and an audit record;
* **authorised** - a ``requires_confirmation`` response is routed to the approval
  callback before the token is used. The model never sees the token until the user
  has said yes, and never at all if they say no.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import config
from agent import prompts
from agent.classifier import classify
from agent.history import ConversationMemory
from agent.llm import LLM
from agent_controller import extract_json
from mcp_server import audit, policy

ApprovalFn = Callable[[dict[str, Any]], bool | Awaitable[bool]]
EventListener = Callable[[str, dict[str, Any]], None]


# --------------------------------------------------------------------------- results
@dataclass
class ToolCall:
    tool: str
    arguments: dict[str, Any]
    status: str
    summary: str
    duration_ms: float
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool, "arguments": self.arguments, "status": self.status,
            "summary": self.summary, "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class AgentResult:
    status: str                       # ok | needs_input | error | cancelled
    answer: str
    steps: int
    tool_calls: list[ToolCall]
    correlation_id: str
    dry_run: bool
    question: str | None = None
    error: str | None = None
    raw: str | None = None
    confidence: float | None = None
    shortcut: bool = False           # answered by the deterministic classifier

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer": self.answer,
            "question": self.question,
            "steps": self.steps,
            "correlation_id": self.correlation_id,
            "dry_run": self.dry_run,
            "error": self.error,
            "confidence": self.confidence,
            "shortcut": self.shortcut,
            "tool_calls": [call.as_dict() for call in self.tool_calls],
        }


# --------------------------------------------------------------------------- parsing
def parse_decision(raw: str, valid_tools: Sequence[str]) -> tuple[dict[str, Any] | None, str]:
    """Validate one model reply against the agent protocol."""
    payload, error = extract_json(raw or "")
    if payload is None:
        return None, error or "no JSON object in the reply"
    if not isinstance(payload, dict):
        return None, "the reply must be a JSON object"

    action = payload.get("action")
    if action == "final":
        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return None, "the 'final' action needs a non-empty 'answer' string"
        decision: dict[str, Any] = {"action": "final", "answer": answer.strip()}
        raw_confidence = payload.get("confidence")
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
            decision["confidence"] = max(0.0, min(float(raw_confidence), 1.0))
        return decision, ""

    if action == "ask_user":
        question = payload.get("question")
        if not isinstance(question, str) or not question.strip():
            return None, "the 'ask_user' action needs a 'question' string"
        return {"action": "ask_user", "question": question.strip()}, ""

    if action == "tool":
        tool = payload.get("tool")
        if not isinstance(tool, str) or tool not in valid_tools:
            return None, (f"unknown tool {tool!r}; valid tools are "
                          f"{', '.join(valid_tools)}")
        arguments = payload.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return None, "the 'arguments' field must be a JSON object"
        return {"action": "tool", "tool": tool, "arguments": arguments}, ""

    return None, "the 'action' field must be 'tool', 'ask_user' or 'final'"


def _grammar_schema(tools: Sequence[Any]) -> dict[str, Any] | None:
    """Per-tool oneOf schema for llama.cpp grammar-constrained decoding."""
    branches = []
    for tool in tools:
        branches.append({
            "type": "object",
            "properties": {
                "tool": {"type": "string", "const": tool.name},
                "arguments": getattr(tool, "input_schema", None) or {"type": "object"},
            },
            "required": ["tool", "arguments"],
        })
    if not branches:
        return None
    return {"type": "object", "oneOf": branches}


def _as_dict(result: Any) -> dict[str, Any]:
    data = getattr(result, "data", result)
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {"status": "error", "summary": f"Unexpected tool response: {data!r}",
            "payload": {}}


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


# --------------------------------------------------------------------------- loop
class Orchestrator:
    """Drives one request at a time; safe to reuse across requests."""

    def __init__(
        self,
        llm: LLM,
        *,
        client_factory: Callable[[], Any] | None = None,
        approve: ApprovalFn | None = None,
        on_event: EventListener | None = None,
        max_steps: int | None = None,
        max_repairs: int | None = None,
        dry_run: bool | None = None,
        memory: ConversationMemory | None = None,
        use_classifier: bool | None = None,
    ) -> None:
        self.llm = llm
        self.client_factory = client_factory or self._default_client
        self.approve = approve
        self.on_event = on_event
        self.max_steps = max_steps or config.MAX_STEPS
        self.max_repairs = config.MAX_REPAIRS if max_repairs is None else max_repairs
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run
        self.memory = memory if memory is not None else ConversationMemory()
        self.use_classifier = (config.USE_CLASSIFIER if use_classifier is None
                               else use_classifier)
        self._cancelled = False
        self._pending_request: str | None = None      # request being remembered

    # ------------------------------------------------------------------ plumbing
    @staticmethod
    def _default_client():
        from fastmcp import Client

        from mcp_server.server import mcp

        return Client(mcp)

    def _emit(self, event: str, **fields: Any) -> None:
        if self.on_event:
            try:
                self.on_event(event, fields)
            except Exception:            # a bad listener must not break a request
                pass

    # ------------------------------------------------------------------ control
    def cancel(self, reason: str = "cancelled by the operator") -> None:
        """Ask the current request to stop before its next step (panic stop)."""
        self._cancelled = True
        audit.record("cancel", correlation_id=audit.current_correlation(),
                     reason=reason)

    def reset_cancel(self) -> None:
        self._cancelled = False

    # ------------------------------------------------------------------ public API
    async def run(self, user_request: str) -> AgentResult:
        correlation_id = audit.new_correlation_id()
        token = audit.set_correlation(correlation_id)
        started = time.monotonic()
        calls: list[ToolCall] = []
        steps = 0
        repairs = 0

        self._pending_request = user_request
        audit.record("request", correlation_id=correlation_id,
                     text=user_request[:300], dry_run=self.dry_run)
        self._emit("request", text=user_request, correlation_id=correlation_id)

        previous_dry = policy.dry_run_enabled()
        policy.set_dry_run(self.dry_run)
        self._cancelled = False

        shortcut = classify(user_request) if self.use_classifier else None
        if shortcut and shortcut.tool != "__audit__":
            audit.record("classifier", correlation_id=correlation_id,
                         tool=shortcut.tool, matched=shortcut.matched)
            self._emit("classifier", tool=shortcut.tool, matched=shortcut.matched)

        try:
            async with self.client_factory() as client:
                tools = await client.list_tools()
                tool_names = [tool.name for tool in tools]
                if not tool_names:
                    return self._finish("error", "The MCP server published no tools.",
                                        steps, calls, correlation_id,
                                        error="no tools")
                system = prompts.build_system_prompt(tools, dry_run=self.dry_run)
                note = self.memory.context_note()
                if note:
                    system = f"{system}\n\n{note}"
                messages: list[dict[str, str]] = [{"role": "system", "content": system}]
                messages.extend(self.memory.messages())
                messages.append({"role": "user", "content": user_request})
                schema = _grammar_schema(tools)

                # Fast path: an unambiguous request skips inference entirely.
                if shortcut and shortcut.tool != "__audit__":
                    early = await self._run_shortcut(client, shortcut, user_request,
                                                     calls, correlation_id)
                    if early is not None:
                        return early

                while steps < self.max_steps:
                    if self._cancelled:
                        return self._finish("cancelled", "Stopped by the operator.",
                                            steps, calls, correlation_id,
                                            error="cancelled")
                    self._emit("thinking", step=steps + 1)
                    raw = await asyncio.to_thread(self.llm.complete, messages, schema)
                    decision, error = parse_decision(raw, tool_names)

                    if decision is None:
                        repairs += 1
                        audit.record("invalid_decision", correlation_id=correlation_id,
                                     error=error, raw=raw[:400])
                        self._emit("repair", error=error, attempt=repairs)
                        if repairs > self.max_repairs:
                            return self._finish(
                                "error",
                                "The model kept producing unusable output. "
                                f"Last problem: {error}",
                                steps, calls, correlation_id, error=error, raw=raw)
                        messages.append({"role": "assistant", "content": raw})
                        messages.append(prompts.repair_message(error, tool_names))
                        continue

                    if decision["action"] == "final":
                        answer = decision["answer"]
                        confidence = decision.get("confidence")
                        if confidence is not None and confidence < 0.5:
                            answer = f"Not sure, but: {answer}"
                        self._emit("final", answer=answer, confidence=confidence)
                        return self._finish("ok", answer, steps, calls, correlation_id,
                                            raw=raw, confidence=confidence)

                    if decision["action"] == "ask_user":
                        question = decision["question"]
                        audit.record("clarify", correlation_id=correlation_id,
                                     question=question[:300])
                        self._emit("clarify", question=question)
                        return self._finish("needs_input", question, steps, calls,
                                            correlation_id, question=question, raw=raw)

                    # ---- tool call
                    steps += 1
                    tool_name = decision["tool"]
                    arguments = decision["arguments"]
                    audit.record("decision", correlation_id=correlation_id,
                                 tool=tool_name, arguments=arguments,
                                 step=steps, dry_run=self.dry_run)
                    self._emit("call", tool=tool_name, arguments=arguments, step=steps)

                    blocked = self._preflight(tool_name)
                    if blocked is not None:
                        calls.append(ToolCall(
                            tool=tool_name, arguments=arguments,
                            status=str(blocked["status"]),
                            summary=str(blocked["summary"]),
                            duration_ms=0.0, payload=blocked.get("payload", {}),
                        ))
                        self._emit("result", tool=tool_name,
                                   status=blocked["status"],
                                   summary=blocked["summary"], duration_ms=0.0)
                        return self._finish(
                            "cancelled" if blocked["status"] == "cancelled" else "error",
                            str(blocked["summary"]), steps, calls, correlation_id,
                            error=str(blocked.get("payload", {}).get("code", "blocked")))

                    call_started = time.monotonic()
                    try:
                        outcome = await self._execute_tool(client, tool_name, arguments)
                    except Exception as exc:
                        outcome = {"status": "error",
                                   "summary": f"The tool call failed: {exc}",
                                   "payload": {"code": "transport_error"}}
                    duration = (time.monotonic() - call_started) * 1000.0

                    call = ToolCall(
                        tool=tool_name, arguments=arguments,
                        status=str(outcome.get("status", "unknown")),
                        summary=str(outcome.get("summary", "")),
                        duration_ms=duration,
                        payload=outcome.get("payload", {}) or {},
                    )
                    calls.append(call)
                    self._emit("result", tool=tool_name, status=call.status,
                               summary=call.summary, duration_ms=duration)

                    if call.status == "cancelled":
                        return self._finish("cancelled", call.summary, steps, calls,
                                            correlation_id)

                    messages.append({"role": "assistant", "content": raw})
                    messages.append(prompts.observation_message(tool_name, outcome))

                # step budget exhausted
                last = calls[-1].summary if calls else "no tool ran"
                answer = ("I stopped after the maximum number of steps "
                          f"({self.max_steps}). Last result: {last}")
                audit.record("step_limit", correlation_id=correlation_id,
                             steps=steps, dry_run=self.dry_run)
                return self._finish("ok", answer, steps, calls, correlation_id,
                                    error="step limit reached")
        finally:
            policy.set_dry_run(previous_dry)
            audit.record("request_end", correlation_id=correlation_id,
                         steps=steps,
                         duration_ms=round((time.monotonic() - started) * 1000, 1),
                         tool_calls=len(calls))
            audit.reset_correlation(token)

    # ------------------------------------------------------------------ guards
    def _preflight(self, tool_name: str) -> dict[str, Any] | None:
        """Panic switch, battery guard and cancellation, checked before any call."""
        if self._cancelled:
            return {"status": "cancelled",
                    "summary": "Stopped by the operator before this step ran.",
                    "payload": {"code": "cancelled", "retryable": False}}
        try:
            policy.assert_not_panicking(tool_name)
        except policy.PanicActive as exc:
            return {"status": "cancelled", "summary": str(exc),
                    "payload": {"code": "panic", "retryable": False,
                                "user_hint": "Send /resume to re-enable actions."}}
        refusal = policy.battery_guard(tool_name)
        if refusal is not None:
            return {"status": "error", "summary": str(refusal["message"]),
                    "payload": refusal}
        return None

    async def _run_shortcut(self, client: Any, shortcut: Any, user_request: str,
                            calls: list[ToolCall],
                            correlation_id: str) -> AgentResult | None:
        """Execute a classifier match without touching the model."""
        blocked = self._preflight(shortcut.tool)
        if blocked is not None:
            return self._finish("cancelled", str(blocked["summary"]), 0, calls,
                                correlation_id, error="blocked")
        started = time.monotonic()
        self._emit("call", tool=shortcut.tool, arguments=shortcut.arguments, step=1)
        try:
            outcome: dict[str, Any] = await self._execute_tool(
                client, shortcut.tool, shortcut.arguments)
        except Exception as exc:
            outcome = {"status": "error", "summary": f"The tool call failed: {exc}",
                       "payload": {"code": "transport_error"}}
        duration = (time.monotonic() - started) * 1000.0
        call = ToolCall(tool=shortcut.tool, arguments=shortcut.arguments,
                        status=str(outcome.get("status", "unknown")),
                        summary=str(outcome.get("summary", "")),
                        duration_ms=duration,
                        payload=outcome.get("payload", {}) or {})
        calls.append(call)
        self._emit("result", tool=shortcut.tool, status=call.status,
                   summary=call.summary, duration_ms=duration)

        # A shortcut never swallows an approval request: hand it to the model path
        # so the user is asked properly.
        if call.status == "requires_confirmation":
            calls.pop()
            self._emit("fallback", tool=shortcut.tool, reason="needs approval")
            return None
        if call.status in {"cancelled", "error"}:
            return self._finish("cancelled" if call.status == "cancelled" else "error",
                                call.summary, 1, calls, correlation_id,
                                error=call.status)
        return self._finish("ok", call.summary, 1, calls, correlation_id,
                            shortcut=True, confidence=shortcut.confidence)

    async def _execute_tool(self, client: Any, name: str,
                            arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool, handling the confirmation handshake."""
        result = _as_dict(await client.call_tool(name, arguments))
        if result.get("status") != "requires_confirmation":
            return result

        info = {
            "tool": name,
            "arguments": arguments,
            "summary": result.get("summary", ""),
            "warning": (result.get("payload") or {}).get("warning", ""),
            "token": result.get("confirmation_token"),
        }
        self._emit("approval_required", **info)

        if self.approve is None:
            return result                       # caller decides what to do with it

        approved = await _maybe_await(self.approve(info))
        audit.record("approval", correlation_id=audit.current_correlation(),
                     tool=name, approved=bool(approved))
        if not approved:
            return {
                "status": "cancelled",
                "summary": f"Action '{name}' was cancelled by the user; nothing ran.",
                "payload": {"code": "user_declined"},
            }

        token = info.get("token")
        if not token:
            return {"status": "error", "summary": "No confirmation token was issued.",
                    "payload": {"code": "missing_token"}}
        resumed = dict(arguments)
        resumed["confirmation_token"] = token
        return _as_dict(await client.call_tool(name, resumed))

    # ------------------------------------------------------------------ profiles
    async def run_profile(self, name: str) -> AgentResult:
        """Replay a stored routine step by step, through the same guardrails."""
        correlation_id = audit.new_correlation_id()
        token = audit.set_correlation(correlation_id)
        calls: list[ToolCall] = []
        self._pending_request = f"run the '{name}' routine"
        try:
            async with self.client_factory() as client:
                profile = _as_dict(await client.call_tool("get_profile", {"name": name}))
                if profile.get("status") != "success":
                    return self._finish("error", profile.get("summary", "profile not found"),
                                        0, calls, correlation_id, error="profile")
                steps = profile["payload"].get("steps", [])
                for index, step in enumerate(steps, start=1):
                    tool = step.get("tool")
                    arguments = step.get("arguments", {}) or {}
                    self._emit("call", tool=tool, arguments=arguments, step=index)
                    started = time.monotonic()
                    result = await self._execute_tool(client, tool, arguments)
                    calls.append(ToolCall(
                        tool=str(tool), arguments=arguments,
                        status=str(result.get("status")),
                        summary=str(result.get("summary", "")),
                        duration_ms=(time.monotonic() - started) * 1000.0,
                        payload=result.get("payload", {}) or {},
                    ))
                    if result.get("status") == "cancelled":
                        return self._finish("cancelled",
                                            f"Profile '{name}' stopped at step {index}.",
                                            index, calls, correlation_id)
                summary = "; ".join(c.summary for c in calls if c.summary)
                return self._finish("ok", f"Profile '{name}' finished: {summary}",
                                    len(calls), calls, correlation_id)
        finally:
            audit.reset_correlation(token)

    # ------------------------------------------------------------------ helpers
    def _finish(self, status: str, answer: str, steps: int, calls: list[ToolCall],
                correlation_id: str, *, question: str | None = None,
                error: str | None = None, raw: str | None = None,
                confidence: float | None = None,
                shortcut: bool = False) -> AgentResult:
        audit.record("answer", correlation_id=correlation_id, status=status,
                     answer=answer[:400], confidence=confidence)
        self._remember(last_answer=answer, status=status, calls=calls)
        return AgentResult(
            status=status, answer=answer, steps=steps, tool_calls=calls,
            correlation_id=correlation_id, dry_run=self.dry_run,
            question=question, error=error, raw=raw,
            confidence=confidence, shortcut=shortcut,
        )

    def _clear_pending(self) -> None:
        self._pending_request = None

    def _remember(self, last_answer: str, status: str,
                  calls: list[ToolCall]) -> None:
        """Keep conversational context for the next request, not the current one."""
        request: str | None = self._pending_request
        self._clear_pending()
        if not request or status in {"error", "cancelled"}:
            return
        self.memory.add(request, last_answer, [call.tool for call in calls])
