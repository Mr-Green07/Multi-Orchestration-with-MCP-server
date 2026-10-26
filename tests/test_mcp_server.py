import pytest
from fastmcp import Client

from mcp_server.security import create_confirmation_token, verify_and_consume_token
from mcp_server.server import mcp


@pytest.mark.asyncio
async def test_tools_discovery():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]

        expected_tools = [
            "system_telemetry",
            "hardware_control",
            "workspace_fs",
            "app_lifecycle",
            "power_session",
        ]
        for expected in expected_tools:
            assert expected in tool_names, f"Tool {expected} not found in registered tools."

@pytest.mark.asyncio
async def test_system_telemetry_memory():
    """Verify system telemetry retrieves valid memory metrics."""
    async with Client(mcp) as client:
        result = await client.call_tool("system_telemetry", {"metric": "memory"})
        assert result.data["status"] == "success"
        assert result.data["metric_or_action"] == "memory"
        assert "used_bytes" in result.data["payload"]

@pytest.mark.asyncio
async def test_hardware_controls_bounds_validation():
    """Verify that out-of-bounds hardware inputs return an error status."""
    async with Client(mcp) as client:
        result = await client.call_tool("hardware_control", {"target": "volume", "value": 150})
        assert result.data["status"] == "error"
        assert "hardware" in result.data["summary"].lower()

@pytest.mark.asyncio
async def test_workspace_fs_path_traversal_defense():
    """Verify that path traversal attempts outside workspace jail are blocked."""
    async with Client(mcp) as client:
        result = await client.call_tool("workspace_fs", {"action": "list", "relative_path": "../../"})
        assert result.data["status"] == "error"
        assert "forbidden" in result.data["summary"].lower()

@pytest.mark.asyncio
async def test_power_session_confirmation_safeguard():
    """Verify shutdown actions return requires_confirmation rather than running immediately."""
    async with Client(mcp) as client:
        result = await client.call_tool("power_session", {"action": "shutdown"})  # <-- Fixed from "power"
        assert result.data["status"] == "requires_confirmation"
        assert "warning" in result.data["payload"]


def test_confirmation_token_verification_consumes_token():
    token = create_confirmation_token("shutdown", {"target_action": "shutdown"})
    payload = verify_and_consume_token(token, expected_action="shutdown")

    assert payload == {"target_action": "shutdown"}
    assert verify_and_consume_token(token, expected_action="shutdown") is None
