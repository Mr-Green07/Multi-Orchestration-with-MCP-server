from rich import terminal_theme
from rich import terminal_theme
from typing import Literal 
import psutil 
from mcp.server.fastmcp import FastMCP 
# pyrefly: ignore[missing-import]
from schemas import SystemToolResponse

mcp = FastMCP("SystemOperatorServer")

@mcp.tool(annotations = {"readOnlyHint": True})
def system_telemetry(
    metric: Literal["cpu", "memory", "disk", "battery"]
) -> dict:
    if metric == "cpu":
        payload = {
            "usage Percentage": psutil.cpu_percent(interval = 1)
        }

    elif metric == "memory":
        mem = payload.virtual_memory()
        payload = {
            "total_bytes": mem.total,
            "available_bytes": mem.available,
            "used_bytes": mem.used,
            "usage_percent": mem.percent,
        }

    elif metric == "disk":
        disk = psutil.disk_usage("/")
        payload = {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "usage_percent": disk.percent,
        }

    else:
        battery = psutil.sensors_battery()
        payload = {
            "percentage": battery.percent,
            "plugged_in": battery.power_plugged,
            "seconds_left": battery.secsleft,
        }

    response = SystemToolResponse(
        status = "success", 
        metric_or_action = metric,
        payload = payload
    )

    return response.model_dump()


if __name__ == "__main__":
    mcp.run()
    