import logging
import platform
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

try:
    from mcp_server.schemas import SystemToolResponse
except ModuleNotFoundError as exc:
    if exc.name != "mcp_server":
        raise
    from schemas import SystemToolResponse


logger = logging.getLogger(__name__)

HardwareTarget = Literal["volume", "mute", "brightness"]


class HardwareControlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target: HardwareTarget
    value: int = Field(ge=0, le=100)
    # summary: str

def set_volume(value: int) -> None:
    from ctypes import POINTER, cast
    from typing import Any
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    if devices is None:
        raise RuntimeError("No audio output device is available")

    # interface = cast(Any, devices).Activate(
    #     IAudioEndpointVolume._iid_,
    #     CLSCTX_ALL,
    #     None,
    # )
    # volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume = devices.EndpointVolume
    volume.SetMasterVolumeLevelScalar(value / 100.0, None)

def set_mute(value: int) -> None:
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    if devices is None:
        raise RuntimeError("No audio output device is available")

    volume = devices.EndpointVolume
    volume.SetMute(1 if value > 0 else 0, None)

def set_brightness(value: int) -> None:

    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$m = Get-CimInstance -Namespace root/WMI "
        "-ClassName WmiMonitorBrightnessMethods; "
        "if (-not $m) { throw 'Brightness control unavailable' }; "
        f"$m | ForEach-Object {{ "
        f"Invoke-CimMethod -InputObject $_ "
        f"-MethodName WmiSetBrightness "
        f"-Arguments @{{Timeout=1; Brightness={value}}} "
        "| Out-Null }; "
        "Write-Output 'OK'"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=5,
        shell=False,
        check=False,
    )
    if result.returncode != 0 or "OK" not in result.stdout:
        raise RuntimeError(
            "Brightness control failed or is unsopported on this device"
        )


def control_hardware(
    target: HardwareTarget,
    value: int,
) -> SystemToolResponse:
    try:
        args = HardwareControlArgs(target=target, value=value)
        if platform.system() != "Windows":
            return SystemToolResponse(
                status= "error",
                metric_or_action= f"{args.target}_control",
                payload={"code":"unsupported_os"},
                summary="Hardware control is currently supported only in windows",
            )
        if args.target == "volume":
            set_volume(args.value)
        elif args.target == "mute":
            set_mute(args.value)

        elif args.target == "brightness":
            set_brightness(args.value)

        logger.info(
            "Hardware control completed: target=%s, value=%d",
            args.target,
            args.value,
        )

        return SystemToolResponse(
            status="success",
            metric_or_action=f"{args.target}_control",
            payload={"value": args.value},
            summary=f"Windows {args.target} control was updated successfully.",
        )

    except Exception as exc:
        logger.warning(
            "Hardware control failed for %s: %s",
            target,
            type(exc).__name__,
        )

        return SystemToolResponse(
            status="error",
            metric_or_action="hardware_control",
            payload={"code": "operation_failed"},
            summary="The hardware setting could not be changed.",
        )

    