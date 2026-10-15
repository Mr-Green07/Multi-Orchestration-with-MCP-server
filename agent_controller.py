"""
agent_controller.py
====================
The custom agent loop that ties everything together:

    user request
        -> local LLM (generate)
        -> strict-JSON parse + validation
        -> if action == "tool": validate + execute + feed result back
        -> if action == "final": return the answer
        -> else: error / re-prompt
    (stop after MAX_STEPS)

Design notes
------------
* The controller depends on an injected ``generate_fn(messages) -> str`` rather
  than the model directly. This keeps the loop fully testable offline with a
  scripted fake model (see tests/).
* JSON is extracted with a brace-matching scanner that tolerates code fences
  and stray text, then strictly validated against the protocol.
* Every request, raw model response, tool call, tool result and final answer
  is logged.
* All failure modes (invalid JSON, empty output, unknown tool, bad args, tool
  exceptions, OOM, context overflow, step exhaustion) are handled gracefully;
  an unvalidated model command is never executed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import security
import tools
from tools import ToolContext


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
def build_system_prompt() -> str:
    return (
        "You are a fully offline AI agent running on a local machine.\n"
        "You have NO internet access. You cannot browse the web, call online "
        "APIs, or run shell commands. You may only use the tools listed below.\n"
        "\n"
        "STRICT OUTPUT PROTOCOL:\n"
        "Respond with EXACTLY ONE JSON object and nothing else. No Markdown, no "
        "code fences, no commentary before or after the JSON.\n"
        "\n"
        "To call a tool:\n"
        '{ "action": "tool", "tool": "<tool_name>", "arguments": { ... } }\n'
        "\n"
        "To give the final answer:\n"
        '{ "action": "final", "answer": "<your answer>" }\n'
        "\n"
        "Available tools:\n"
        f"{tools.describe_tools()}\n"
        "\n"
        "RULES:\n"
        "- Never invent a tool that is not in the list above.\n"
        "- Never request shell execution, file deletion, or network access.\n"
        "- Use a tool ONLY when it is needed to answer; otherwise answer directly "
        "with action 'final'.\n"
        "- After a tool result is provided, use it to produce a final answer (or "
        "call another allowed tool if truly necessary).\n"
        "- If a tool fails, explain the failure plainly in your final answer.\n"
        "- Never claim you performed an action that is not available to you.\n"
        "- For document questions, call search_documents and answer ONLY from the "
        "returned context. If the context is insufficient, say the answer is not "
        "available in the provided documents.\n"
        "- Be concise and factual."
    )


# ---------------------------------------------------------------------------
# Strict JSON extraction
# ---------------------------------------------------------------------------
def extract_json(text: str):
    """Extract the first balanced JSON object from *text*.

    Returns ``(obj, None)`` on success or ``(None, error_message)``.
    Tolerates code fences and surrounding prose; ignores braces inside strings.
    """
    if not text or not text.strip():
        return None, "empty output"

    start = text.find("{")
    if start == -1:
        return None, "no JSON object found in the output"

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate), None
                except json.JSONDecodeError as exc:
                    return None, f"JSON decode error: {exc.msg}"
    return None, "unbalanced braces in output"


def validate_action(obj: Any):
    """Validate the parsed object against the protocol.

    Returns ``(kind, payload, error)`` where kind is 'tool' | 'final' | None.
    """
    if not isinstance(obj, dict):
        return None, None, "top-level JSON must be an object"
    action = obj.get("action")
    if action == "final":
        answer = obj.get("answer")
        if answer is None:
            return None, None, "final action is missing the 'answer' field"
        return "final", str(answer), None
    if action == "tool":
        tool_name = obj.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            return None, None, "tool action is missing a valid 'tool' name"
        arguments = obj.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return None, None, "'arguments' must be a JSON object"
        return "tool", {"tool": tool_name, "arguments": arguments}, None
    return None, None, f"unknown or missing action: {action!r} (expected 'tool' or 'final')"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class AgentResult:
    answer: str
    steps: int
    exhausted: bool = False
    error: Optional[str] = None
    trace: List[dict] = field(default_factory=list)
    tool_calls: List[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------
class AgentController:
    def __init__(
        self,
        generate_fn: Callable[[List[dict]], str],
        ctx: ToolContext,
        logger=None,
        max_steps: int = security.MAX_STEPS,
        show_tools: bool = False,
        max_history_messages: int = 8,
    ):
        self.generate = generate_fn
        self.ctx = ctx
        self.logger = logger or security.get_logger()
        self.max_steps = max_steps
        self.show_tools = show_tools
        self.max_history_messages = max_history_messages
        self.history: List[dict] = []  # persisted user/assistant turns across requests

    # -- history management --
    def clear(self) -> None:
        self.history = []

    def _trim_history(self) -> None:
        if len(self.history) > self.max_history_messages:
            self.history = self.history[-self.max_history_messages:]

    # -- main entry point --
    def run(self, user_input: str) -> AgentResult:
        self.ctx.reset_counters()
        self.logger.info("USER_REQUEST: %s", user_input)

        messages: List[dict] = (
            [{"role": "system", "content": build_system_prompt()}]
            + list(self.history)
            + [{"role": "user", "content": user_input}]
        )

        trace: List[dict] = []
        tool_calls: List[dict] = []
        last_error: Optional[str] = None

        step = 0
        while step < self.max_steps:
            step += 1

            # --- generate ---
            try:
                raw = self.generate(messages)
            except Exception as exc:
                friendly = self._handle_generation_error(exc)
                self.logger.error("GENERATION_ERROR (step %d): %s", step, exc)
                return self._finish(user_input, friendly, step, trace, tool_calls,
                                    exhausted=False, error=str(exc))

            raw = raw or ""
            self.logger.info("MODEL_RESPONSE (step %d): %s", step, security.truncate(raw, 1000))
            trace.append({"step": step, "type": "model_raw", "content": raw})

            # --- empty output ---
            if not raw.strip():
                last_error = "empty model output"
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content":
                                 "Your previous response was empty. Respond with exactly one "
                                 "JSON object following the protocol."})
                continue

            # --- parse JSON ---
            obj, perr = extract_json(raw)
            if obj is None:
                last_error = perr
                self.logger.warning("JSON_PARSE_FAIL (step %d): %s", step, perr)
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content":
                                 f"Your output was not valid JSON ({perr}). Respond with exactly "
                                 "one JSON object and no other text."})
                continue

            # --- validate protocol ---
            kind, payload, verr = validate_action(obj)
            if kind is None:
                last_error = verr
                self.logger.warning("PROTOCOL_FAIL (step %d): %s", step, verr)
                messages.append({"role": "assistant", "content": json.dumps(obj)})
                messages.append({"role": "user", "content":
                                 f"Protocol error: {verr}. Use action 'tool' or 'final' in one "
                                 "JSON object."})
                continue

            # --- final answer ---
            if kind == "final":
                self.logger.info("FINAL_ANSWER (step %d): %s", step, security.truncate(payload, 1000))
                return self._finish(user_input, payload, step, trace, tool_calls, exhausted=False)

            # --- tool call ---
            tool_name = payload["tool"]
            arguments = payload["arguments"]
            self.logger.info("TOOL_CALL (step %d): %s args=%s", step, tool_name,
                             security.truncate(json.dumps(arguments), 500))
            if self.show_tools:
                print(f"  [tool call] {tool_name}({json.dumps(arguments, ensure_ascii=False)})")

            result = tools.run_tool(tool_name, arguments, self.ctx)
            result_text = tools.result_to_text(result)
            self.logger.info("TOOL_RESULT (step %d): %s", step, security.truncate(result_text, 1000))
            trace.append({"step": step, "type": "tool_result", "tool": tool_name, "result": result})
            tool_calls.append({"tool": tool_name, "arguments": arguments, "result": result})
            if self.show_tools:
                status = "ok" if result.get("ok") else "error"
                print(f"  [tool result: {status}] {security.truncate(result_text, 500)}")

            messages.append({"role": "assistant",
                             "content": json.dumps({"action": "tool", "tool": tool_name,
                                                    "arguments": arguments})})
            messages.append({"role": "user", "content":
                             f"TOOL_RESULT for {tool_name}: {result_text}\n"
                             "Now respond with exactly one JSON object: either action 'final' with "
                             "the answer, or another allowed tool call if strictly necessary."})

        # --- step budget exhausted ---
        fallback = (f"I reached the maximum of {self.max_steps} reasoning steps without producing a "
                    "final answer.")
        if last_error:
            fallback += f" Last issue: {last_error}."
        self.logger.warning("MAX_STEPS_EXCEEDED: %s", fallback)
        return self._finish(user_input, fallback, step, trace, tool_calls,
                            exhausted=True, error=last_error)

    # -- helpers --
    def _finish(self, user_input, answer, steps, trace, tool_calls, exhausted, error=None):
        # Persist a compact view of this exchange for multi-turn context.
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant",
                             "content": json.dumps({"action": "final", "answer": answer})})
        self._trim_history()
        return AgentResult(answer=answer, steps=steps, exhausted=exhausted,
                           error=error, trace=trace, tool_calls=tool_calls)

    @staticmethod
    def _handle_generation_error(exc: Exception) -> str:
        name = exc.__class__.__name__
        msg = str(exc).lower()
        if name == "OutOfMemoryError" or "out of memory" in msg or "cuda oom" in msg:
            return ("The model ran out of GPU memory while generating a response. "
                    "Try a shorter request, reduce --max-new-tokens, or restart the agent.")
        if "maximum context" in msg or "context length" in msg or "too long" in msg or "index out of range" in msg:
            return ("The conversation exceeded the model's context window. "
                    "Use '/clear' to reset the conversation and try again.")
        return f"The model failed to generate a response ({name}: {exc})."
