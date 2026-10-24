from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class SystemToolResponse(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    status: Literal["success", "error", "pending_approval", "requires_confirmation"]
    metric_or_action: str = Field(
        ...,
        min_length = 1,
        description = "Name of the metric checked or action performed.",
    )
    payload: dict[str, Any] = Field(
        default_factory = dict,
        description = "Compact structured data containing results or error details.",
    )
    summary: str = Field(
        ...,
        min_length=1,
        description="One sentence human readable summary for the tarui UI.",
    )
    confirmation_token: Optional[str] = None