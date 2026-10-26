"""mcp_server/schemas.py
=====================
The single response contract for every tool.

Adding fields here is cheap and backwards compatible for clients that ignore
unknown keys, but ``extra="forbid"`` keeps the *server* honest: a tool cannot
accidentally emit a field the schema does not declare.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolStatus = Literal[
    "success",          # the action ran and was verified
    "error",            # rejected or failed; nothing changed
    "requires_confirmation",  # a token was issued; the action has not run
    "cancelled",        # the user declined
    "dry_run",          # would have run; nothing was executed
    "unsupported",      # capability missing on this host
    "rate_limited",     # refused by the rate limiter
    "pending_approval", # reserved for asynchronous approval flows
]


class SystemToolResponse(BaseModel):
    """Uniform tool result: status, name, summary, payload, optional extras."""

    model_config = ConfigDict(extra="forbid")

    status: ToolStatus
    metric_or_action: str = Field(
        ..., min_length=1,
        description="Name of the metric checked or action performed.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Compact structured data containing results or error details.",
    )
    summary: str = Field(
        ..., min_length=1,
        description="One sentence human readable summary for the terminal UI.",
    )
    confirmation_token: str | None = None
    correlation_id: str | None = None
    applied: bool | None = Field(
        default=None,
        description="True when the intended effect was verified after execution.",
    )
    previous: dict[str, Any] | None = Field(
        default=None,
        description="State captured before a reversible change, for undo.",
    )
