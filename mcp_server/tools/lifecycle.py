import sys
import subprocess 
from typing import Literal, Optional
from enum import Enum 
from schemas import SystemToolResponse

class AllowedApps(str, Enum): #list of applicaiton which are being used for testing in mcp server
    VSCODE = "vscode",
    BROWSER = "browser"
    TERMINAL = "terminal"
    CALCULATOR = "calculator"

def execute_app_lifecycle(
    action: Literal["launch", "list_running", "request_kill"],
    app_name: Optional[AllowedApps] = None,
    pid: Optional[int] = None
) -> dict:
    try:
        if action == "list_running": #execute when asked to list application
            import psutil 
            running_apps = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']): #check for the applicaiton by process id, name and memory usage
                try:
                    if proc.info['memory_percent'] and proc.info['memory_percent'] > 0.5:
                        running_apps.append({
                            "pid": proc.info['pid'],
                            "name": proc.info['name'],
                            "memory_percent": round(proc.info['memory_percent'], 2)
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            running_apps = sorted(running_apps, key= lambda x: x['memory_percent'], reverse=True)[:10] #sort the max memory consuming application
            return SystemToolResponse(
                status= "success",
                metric_or_action= "list_running_apps",
                summary = f"Retrieved top {len(running_apps)} active processes.",
                payload = {"process": running_apps}
            ).model_dump()

        elif action == "launch": #execute when asked to launch specific application which is in list
            if not app_name:
                return SystemToolResponse(
                    status="error",
                    metric_or_action="launch_app",
                    summary="Missing 'app_name' parameter for launch action.",
                    payload={"error": "app_name required"}
                ).model_dump()
            
            if sys.platform == "win32": # first check the platform where the command is getting executed
                app_commands = {
                    AllowedApps.VSCODE: ["code"],
                    AllowedApps.BROWSER: ["start", "Chrome"],
                    AllowedApps.TERMINAL: ["wt"],
                    AllowedApps.CALCULATOR: ["calc"]
                }
                cmd = app_commands.get(app_name)
                if cmd:
                    subprocess.Popen(cmd, shell=True)

            return SystemToolResponse(
                status="success",
                metric_or_action="launch_app",
                summary=f"Successfully launched {app_name.value}.",
                payload={"launched_app": app_name.value}
            ).model_dump()

        elif action == "request_kill": #asked to close the application after confirmation 
            if not pid:
                return SystemToolResponse(
                    status="error",
                    metric_or_action="request_kill",
                    summary="Missing 'pid' parameter for process termination.",
                    payload={"error": "pid required"}
                ).model_dump()
            
            return SystemToolResponse(
                status="requires_confirmation", # type: ignore
                metric_or_action="request_kill",
                summary=f"Kill request for PID {pid} requires user confirmation.",
                payload={"target_pid": pid, "warning": "Destructive action"}
            ).model_dump()


        else:
            return SystemToolResponse(
                status="error",
                metric_or_action="app_lifecycle",
                summary="Invalid action specified.",
                payload={"error": "Unsupported action"}
            ).model_dump()

    except Exception as e:
        return SystemToolResponse(
            status="error",
            metric_or_action="app_lifecycle",
            summary="Failed to execute application lifecycle action.",
            payload={"error": str(e)}
        ).model_dump()