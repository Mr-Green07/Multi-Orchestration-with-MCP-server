import sys
import subprocess
from typing import Literal
from mcp_server.schemas import SystemToolResponse

def execute_power_session(
    action: Literal["lock_screen", "sleep", "restart", "shutdown"]
) -> dict: # type: ignore
    try:
        if action == "lock_screen":
            if sys.platform == "win32":
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
            elif sys.platform == "darwin":
                subprocess.run(["pmset", "displaysleepnow"], check=True)
            else:  # Linux (freedesktop screensaver lock)
                subprocess.run(["xdg-screensaver", "lock"], check=True)

            return SystemToolResponse(
                status="success",
                metric_or_action="lock_screen",
                summary="Screen locked successfully.",
                payload={"action": "lock_screen"}
            ).model_dump()

        elif action == "sleep":
            if sys.platform == "win32":
                # Put Windows to sleep (requires SuspendState API call)
                subprocess.run(
                    ["powershell", "-Command", "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"],
                    check=True
                )
            elif sys.platform == "darwin":
                subprocess.run(["pmset", "sleepnow"], check=True)
            else:  # Linux systemd sleep
                subprocess.run(["systemctl", "suspend"], check=True)

            return SystemToolResponse(
                status="success",
                metric_or_action="sleep",
                summary="System entering sleep mode.",
                payload={"action": "sleep"}
            ).model_dump()

        elif action in ["restart", "shutdown"]: #it needs two phase authorization to make changes as it total power off the system.
            # Tier 3 Guardrail: Destructive actions must never execute without confirmation
            return SystemToolResponse(
                status="requires_confirmation", # type: ignore
                metric_or_action=action,
                summary=f"System {action} requested. Requires explicit confirmation token before executing.",
                payload={
                    "target_action": action,
                    "warning": f"Executing {action} will terminate active tasks and close all running applications."
                }
            ).model_dump()

        else:
            return SystemToolResponse(
                status="error",
                metric_or_action="power_session",
                summary="Unsupported power session action.",
                payload={"error": "Invalid action"}
            ).model_dump()

    except Exception as e:
        return SystemToolResponse(
            status="error",
            metric_or_action="power_session",
            summary=f"Failed to execute power action '{action}'.",
            payload={"error": str(e)}
        ).model_dump()