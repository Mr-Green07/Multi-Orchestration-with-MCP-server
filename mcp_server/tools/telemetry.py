"""mcp_server/tools/telemetry.py
=============================
Read-only awareness tools.

Design notes:

* no sampling call blocks the event loop for a second - CPU is sampled with a
  0.1 s interval and everything else is instantaneous;
* ``machine_health`` answers the question a user actually asks ("is my machine
  okay?") in one call, with a verdict and a severity;
* the network tool reports interface state and throughput only. It deliberately
  performs **no** connectivity probe, because "zero outbound packets" is a
  guarantee of this project.
"""
from __future__ import annotations

import shutil
import time
from typing import Any, Literal

import psutil

from mcp_server import policy
from mcp_server.tools._common import respond, unsupported

Metric = Literal["cpu", "memory", "disk", "battery"]


# --------------------------------------------------------------------------- primitives
def _cpu_payload() -> dict[str, Any]:
    per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    return {
        "usage_percent": round(psutil.cpu_percent(interval=None), 1),
        "per_core_percent": per_core,
        "core_count": psutil.cpu_count(),
        "load_average": [round(v, 2) for v in (psutil.getloadavg()
                                               if hasattr(psutil, "getloadavg") else (0, 0, 0))],
    }


def _memory_payload() -> dict[str, Any]:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total_bytes": mem.total,
        "available_bytes": mem.available,
        "used_bytes": mem.used,
        "usage_percent": mem.percent,
        "swap_usage_percent": swap.percent,
    }


def _disk_payload() -> dict[str, Any]:
    root = "/" if policy.host_platform() != "win32" else "C:\\"
    usage = psutil.disk_usage(root)
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "usage_percent": usage.percent,
        "path": root,
    }


def _battery_payload() -> dict[str, Any]:
    battery = psutil.sensors_battery()
    if battery is None:
        return {"percentage": None, "plugged_in": None, "seconds_left": None}
    return {
        "percentage": battery.percent,
        "plugged_in": battery.power_plugged,
        "seconds_left": None if battery.secsleft in (psutil.POWER_TIME_UNLIMITED,
                                                     psutil.POWER_TIME_UNKNOWN)
        else battery.secsleft,
    }


def system_telemetry(metric: Metric, correlation_id: str | None = None) -> dict:
    builders = {
        "cpu": _cpu_payload,
        "memory": _memory_payload,
        "disk": _disk_payload,
        "battery": _battery_payload,
    }
    builder = builders.get(metric)
    if builder is None:
        return respond(tool="system_telemetry", action="system_telemetry", status="error",
                       summary=f"Unknown metric '{metric}'.",
                       payload={"allowed": sorted(builders)},
                       correlation_id=correlation_id)
    payload = builder()
    return respond(tool="system_telemetry", action=metric, status="success",
                   summary=f"{metric} telemetry retrieved",
                   payload=payload, arguments={"metric": metric},
                   correlation_id=correlation_id)


# --------------------------------------------------------------------------- aggregates
def disk_inventory(correlation_id: str | None = None) -> dict:
    rows = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        rows.append({
            "device": part.device,
            "mountpoint": part.mountpoint,
            "fstype": part.fstype,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "usage_percent": usage.percent,
        })
    rows.sort(key=lambda r: r["usage_percent"], reverse=True)
    return respond(tool="disk_inventory", action="disk_inventory", status="success",
                   summary=f"Inspected {len(rows)} mounted volumes.",
                   payload={"volumes": rows}, correlation_id=correlation_id)


def network_status(correlation_id: str | None = None) -> dict:
    before = {name: psutil.net_io_counters(pernic=True).get(name)
              for name in psutil.net_io_counters(pernic=True)}
    time.sleep(0.2)
    after = psutil.net_io_counters(pernic=True)
    interfaces = []
    for name, counters in after.items():
        prev = before.get(name)
        stats = psutil.net_if_stats().get(name)
        interfaces.append({
            "name": name,
            "is_up": bool(stats.isup) if stats else None,
            "speed_mbps": stats.speed if stats else None,
            "rx_bytes": counters.bytes_recv,
            "tx_bytes": counters.bytes_sent,
            "rx_rate_kbps": round(((counters.bytes_recv - prev.bytes_recv) / 0.2 / 1024), 1)
            if prev else 0.0,
            "tx_rate_kbps": round(((counters.bytes_sent - prev.bytes_sent) / 0.2 / 1024), 1)
            if prev else 0.0,
        })
    active = [i for i in interfaces if i["is_up"]]
    return respond(
        tool="network_status", action="network_status", status="success",
        summary=f"{len(active)} network interface(s) up; no connectivity probe performed.",
        payload={"interfaces": interfaces, "active_count": len(active),
                 "note": "Interface statistics only - the agent never sends packets."},
        correlation_id=correlation_id,
    )


def gpu_status(correlation_id: str | None = None) -> dict:
    if shutil.which("nvidia-smi"):
        import subprocess

        try:
            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,"
                               "utilization.gpu,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, shell=False, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0 and proc.stdout.strip():
            gpus = []
            for line in proc.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    gpus.append({"name": parts[0], "memory_total_mb": parts[1],
                                 "memory_used_mb": parts[2], "utilisation_percent": parts[3],
                                 "temperature_c": parts[4]})
            return respond(tool="gpu_status", action="gpu_status", status="success",
                           summary=f"Reported {len(gpus)} GPU(s) via nvidia-smi.",
                           payload={"gpus": gpus, "backend": "nvidia-smi"},
                           correlation_id=correlation_id)
    return unsupported("gpu_status", "gpu_status",
                       "No GPU telemetry backend is available.",
                       hint="Install the NVIDIA driver (nvidia-smi) to enable GPU metrics.")


def top_processes(limit: int = 8, sort: str = "memory",
                  correlation_id: str | None = None) -> dict:
    from mcp_server.tools.lifecycle import _process_snapshot

    rows = _process_snapshot()
    key = "cpu_percent" if sort == "cpu" else "memory_percent"
    rows = [r for r in rows if r[key] > 0]
    rows.sort(key=lambda r: (r[key], r["memory_percent"]), reverse=True)
    top = rows[: max(1, min(limit, 20))]
    return respond(
        tool="top_processes", action="top_processes", status="success",
        summary=f"Top {len(top)} processes by {sort.replace('_percent', '')}.",
        payload={"processes": top, "sorted_by": sort}, correlation_id=correlation_id,
    )


def machine_health(correlation_id: str | None = None) -> dict:
    """One call that answers "is this machine okay?"."""
    cpu = _cpu_payload()
    memory = _memory_payload()
    disk = _disk_payload()
    battery = _battery_payload()

    issues: list[dict[str, str]] = []
    severity = "ok"

    if memory["usage_percent"] >= 90:
        issues.append({"level": "critical", "what": "memory",
                       "detail": f"RAM at {memory['usage_percent']}%"})
        severity = "critical"
    elif memory["usage_percent"] >= 80:
        issues.append({"level": "warning", "what": "memory",
                       "detail": f"RAM at {memory['usage_percent']}%"})
        severity = "warning" if severity == "ok" else severity

    if disk["usage_percent"] >= 95:
        issues.append({"level": "critical", "what": "disk",
                       "detail": f"Disk at {disk['usage_percent']}%"})
        severity = "critical"
    elif disk["usage_percent"] >= 85:
        issues.append({"level": "warning", "what": "disk",
                       "detail": f"Disk at {disk['usage_percent']}%"})
        severity = "warning" if severity == "ok" else severity

    if cpu["usage_percent"] >= 90:
        issues.append({"level": "warning", "what": "cpu",
                       "detail": f"CPU at {cpu['usage_percent']}%"})
        severity = "warning" if severity == "ok" else severity

    if battery["percentage"] is not None and battery["plugged_in"] is False \
            and battery["percentage"] <= 20:
        issues.append({"level": "warning", "what": "battery",
                       "detail": f"Battery at {battery['percentage']}% and discharging"})
        severity = "warning" if severity == "ok" else severity

    uptime_hours = round((time.time() - psutil.boot_time()) / 3600, 1)
    verdict = {
        "ok": "Machine looks healthy.",
        "warning": "Machine is under pressure: " + "; ".join(i["detail"] for i in issues),
        "critical": "Machine needs attention: " + "; ".join(i["detail"] for i in issues),
    }[severity]

    return respond(
        tool="machine_health", action="machine_health", status="success",
        summary=verdict,
        payload={
            "cpu": cpu, "memory": memory, "disk": disk, "battery": battery,
            "uptime_hours": uptime_hours, "issues": issues, "severity": severity,
            "verdict": verdict,
            "platform": policy.platform_label(),
        },
        correlation_id=correlation_id,
    )
