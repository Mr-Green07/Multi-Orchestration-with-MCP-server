from typing import Literal, Optional
import psutil 
from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pathlib import Path
from pydantic import Field
from mcp_server.tools.lifecycle import execute_app_lifecycle, AllowedApps
from mcp_server.tools.workspace import execute_workspace_fs
# try:
from config import WORKSPACE_JAIL_ROOT
# except ModuleNotFoundError as exc:
#     if exc.name != "config":
#         raise
#     import sys

#     project_root = Path(__file__).resolve().parent
#     if str(project_root) not in sys.path:
#         sys.path.insert(0, str(project_root))
#     from config import WORKSPACE_JAIL_ROOT

try:
    from mcp_server.tools.hardware_controls import control_hardware, HardwareControlArgs
except ModuleNotFoundError as exc:
    if exc.name != "mcp_server":
        raise
    from tools.hardware_controls import control_hardware, HardwareControlArgs



try: 
    from mcp_server.schemas import SystemToolResponse
except ImportError:
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
        mem = psutil.virtual_memory()
        payload = {
            "total_bytes": mem.total,
            "available_bytes": mem.available,
            "used_bytes": mem.used,
            "usage_percent": mem.percent,
        }

    elif metric == "disk":
        disk = psutil.disk_usage(Path.cwd().anchor)
        payload = {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "usage_percent": disk.percent,
        }

    else:
        battery = psutil.sensors_battery()
        if battery is None:
            payload = {
                "percentage": None,
                "plugged_in": None,
                "seconds_left": None,
            }
        else:
            payload = {
                "percentage": battery.percent,
                "plugged_in": battery.power_plugged,
                "seconds_left": battery.secsleft,
            }

    response = SystemToolResponse(
        status = "success", 
        metric_or_action = metric,
        summary = f"{metric} telemetry retrieved",
        payload = payload
    )

    return response.model_dump()

from typing import Literal

HardwareTarget = Literal["volume", "mute", "brightness"]

@mcp.tool()
def hardware_control(
    target: HardwareControlArgs.model_fields["target"].annotation, # type: ignore
    value: int,
) -> dict:
    """Set Windows volume, mute, or brightness."""
    result = control_hardware(target, value)
    return result.model_dump()


@mcp.tool(annotations = {"readOnlyHint": True}) #connecting tool to direct mcp server and call it
def app_lifecycle(
    action: Literal["launch", "list_running", "request_kill"],
    app_name: Optional[AllowedApps] = None,
    pid: Optional[int] = None
) -> dict:
    return execute_app_lifecycle(action, app_name, pid)

@mcp.tool(annotations={"readOnlyHint": False})
def workspace_fs(
    action: Literal["list", "read_text", "search"],
    relative_path: str = "",
    search_query: Optional[str] = None
) -> dict:
    """Safely inspect, read, or search files within the sandboxed workspace folder."""
    return execute_workspace_fs(action, relative_path, search_query)

if __name__ == "__main__":
    mcp.run()
