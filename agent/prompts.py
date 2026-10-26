"""agent/prompts.py
================
Prompt construction.

The prompt is generated from the tools the server actually publishes, so adding a
sixth tool to the server changes the agent's behaviour with no code change here.
Each tool gets a compact argument signature plus one worked example, because a
four-billion-parameter model is far more reliable at copying a shape than at
inferring one.
"""
from __future__ import annotations

import json
import platform
from collections.abc import Sequence
from typing import Any

import config

PROTOCOL = """STRICT OUTPUT PROTOCOL
Reply with exactly one JSON object and nothing else. No prose, no markdown.
  call a tool : {"action":"tool","tool":"<name>","arguments":{...}}
  ask a human : {"action":"ask_user","question":"..."}
  answer      : {"action":"final","answer":"..."}"""

RULES = """RULES
- Use only the tools and argument names listed above. Never invent either.
- Prefer one tool call per step; you will see the result and may call again.
- Ask the user when the request is ambiguous or the target is unclear.
- Never claim an action happened unless a tool result says it did.
- If a tool returns status "requires_confirmation", the user will be asked; do
  not try to bypass it.
- Answer in plain language, briefly, using the values from the tool result.
- Destructive or unavailable actions: explain instead of guessing."""


def _argument_summary(schema: dict[str, Any]) -> str:
    props: dict[str, Any] = (schema or {}).get("properties", {}) or {}
    required = set((schema or {}).get("required", []) or [])
    parts = []
    for name, spec in props.items():
        if "enum" in spec:
            kind = "|".join(str(v) for v in spec["enum"])
        elif "anyOf" in spec:
            kinds = [s.get("type") for s in spec["anyOf"] if s.get("type") != "null"]
            kind = "/".join(k for k in kinds if k) or "any"
        else:
            kind = spec.get("type", "any")
        marker = "" if name in required else "?"
        parts.append(f"{name}{marker}:{kind}")
    return ", ".join(parts) or "no arguments"


def _example_for(tool_name: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Build one valid example call from the schema's own defaults and enums."""
    props: dict[str, Any] = (schema or {}).get("properties", {}) or {}
    required = set((schema or {}).get("required", []) or [])
    example: dict[str, Any] = {}
    for name, spec in props.items():
        if name not in required and "default" not in spec:
            continue
        if "enum" in spec and spec["enum"]:
            example[name] = spec["enum"][0]
        elif "default" in spec:
            example[name] = spec["default"]
        elif spec.get("type") == "integer":
            example[name] = 1
        elif spec.get("type") == "boolean":
            example[name] = True
        else:
            example[name] = "example"
    if not example:
        return None
    return {"action": "tool", "tool": tool_name, "arguments": example}


def describe_tools(tools: Sequence[Any]) -> str:
    lines = []
    for index, tool in enumerate(tools, start=1):
        schema = getattr(tool, "input_schema", None) or {}
        description = (getattr(tool, "description", "") or "").strip().splitlines()
        headline = description[0] if description else "no description"
        lines.append(f"{index}. {tool.name}  ({_argument_summary(schema)})")
        lines.append(f"   {headline}")
    return "\n".join(lines)


def build_system_prompt(tools: Sequence[Any], dry_run: bool | None = None) -> str:
    dry = config.DRY_RUN if dry_run is None else dry_run
    examples = [ex for ex in (_example_for(t.name, getattr(t, "input_schema", {}) or {})
                              for t in tools[:4]) if ex]
    example_block = "\n".join(json.dumps(ex, separators=(",", ":")) for ex in examples)
    mode = ("DRY RUN: no action will be executed; results are simulated."
            if dry else "Live mode: tools act on this computer.")

    return f"""You are the planner of a local system-operations agent running on the
user's own computer. Everything runs offline; there is no internet access.
{mode}

ENVIRONMENT
  platform : {platform.system()} {platform.release()}
  workspace: {config.WORKSPACE_JAIL_ROOT} (the only folder you may touch)

TOOLS (discovered live from the MCP server)
{describe_tools(tools)}

EXAMPLE CALLS
{example_block}

{PROTOCOL}

{RULES}"""


def repair_message(error: str, allowed_tools: Sequence[str]) -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "Your previous reply could not be used: " + error +
            "\nReply again with exactly one JSON object. "
            "Valid tool names: " + ", ".join(allowed_tools) + "."
        ),
    }


def observation_message(tool: str, result: dict[str, Any]) -> dict[str, str]:
    """Compact the tool result before it re-enters the prompt."""
    summary = result.get("summary", "")
    payload = result.get("payload", {})
    body = json.dumps(payload, ensure_ascii=False, default=str)
    if len(body) > 1200:
        body = body[:1200] + "...[truncated]"
    return {
        "role": "user",
        "content": (
            f"TOOL RESULT for {tool}\n"
            f"status: {result.get('status')}\n"
            f"summary: {summary}\n"
            f"payload: {body}\n\n"
            "Decide the next step: call another tool, ask the user, or give the final answer."
        ),
    }
