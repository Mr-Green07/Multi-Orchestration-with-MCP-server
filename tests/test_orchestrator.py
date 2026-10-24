import json
import pytest
from unittest.mock import MagicMock, patch
from orchestrator.agent import SystemAgentOrchestrator

@pytest.mark.asyncio
@patch("orchestrator.agent.MODEL_PATH")
@patch("orchestrator.agent.Llama")
async def test_orchestrator_routes_telemetry(mock_llama_cls, mock_path):
    """Verify orchestrator parses LLM JSON decision and calls FastMCP server."""
    mock_path.exists.return_value = True
    mock_path.name = "model.gguf"

    mock_llm_instance = MagicMock()
    mock_llm_instance.create_chat_completion.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "tool": "system_telemetry",
                    "arguments": {"metric": "cpu"}
                })
            }
        }]
    }
    mock_llama_cls.return_value = mock_llm_instance

    agent = SystemAgentOrchestrator()
    result = await agent.execute_query("What is my CPU usage?")

    assert result["status"] == "success"
    assert result["metric_or_action"] == "cpu"
    assert "usage Percentage" in result["payload"] or "usage_percent" in result["payload"]

@pytest.mark.asyncio
async def test_two_phase_confirmation_token_flow():
    """Verify power_session requires a token first, then rejects invalid tokens."""
    from fastmcp import Client
    from mcp_server.server import mcp

    async with Client(mcp) as client:
        # Step 1: Request shutdown without token
        res1 = await client.call_tool("power_session", {"action": "shutdown"})
        assert res1.data["status"] == "requires_confirmation"
        token = res1.data.get("confirmation_token")
        assert token is not None

        # Step 2: Supply a fake token and verify rejection
        res2 = await client.call_tool(
            "power_session",
            {"action": "shutdown", "confirmation_token": "invalid_token_123"}
        )
        assert res2.data["status"] == "error"
        assert "invalid" in res2.data["summary"].lower()