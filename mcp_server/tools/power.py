import sys
import subprocess
from typing import Literal, Optional
from mcp_server.schemas import SystemToolResponse
from mcp_server.security import create_confirmation_token, verify_and_consume_token

def execute_power_session(
    action: Literal["lock_screen", "sleep", "restart", "shutdown"],
    confirmation_token: Optional[str] = None
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
        elif action in ["restart", "shutdown"]:
            # Phase 1 of Confirmation: No token supplied -> issue token and halt
            if not confirmation_token:
                token = create_confirmation_token(action, {"target_action": action})
                return SystemToolResponse(
                    status="requires_confirmation",
                    metric_or_action=action,
                    summary=f"System {action} requested. Requires explicit confirmation.",
                    payload={
                        "target_action": action,
                        "warning": f"Executing {action} will close all active applications."
                    },
                    confirmation_token=token # type: ignore
                ).model_dump()

            # Phase 2 of Confirmation: Verify token and execute
            verified = verify_and_consume_token(confirmation_token, expected_action=action)
            if not verified:
                return SystemToolResponse(
                    status="error",
                    metric_or_action=action,
                    summary="Invalid or expired confirmation token.",
                    payload={"error": "Confirmation rejected"}
                ).model_dump()

            # Token verified! Execute actual OS command
            if sys.platform == "win32":
                flag = "/r" if action == "restart" else "/s"
                subprocess.run(["shutdown", flag, "/t", "5"], check=True)
            else:
                cmd = "reboot" if action == "restart" else "poweroff"
                subprocess.run(["systemctl", cmd], check=True)

            return SystemToolResponse(
                status="success",
                metric_or_action=action,
                summary=f"Confirmed! System {action} initiated (5s grace period).",
                payload={"action": action, "confirmed": True}
            ).model_dump()

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