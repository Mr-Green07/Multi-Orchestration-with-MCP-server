"""Telemetry tools: metrics, health verdict, inventory, privacy of the network tool."""
from __future__ import annotations

import psutil
import pytest

from mcp_server.tools import telemetry


@pytest.mark.parametrize("metric,expected_key", [
    ("cpu", "usage_percent"),
    ("memory", "used_bytes"),
    ("disk", "free_bytes"),
    ("battery", "percentage"),
])
def test_each_metric_returns_its_payload(metric, expected_key):
    result = telemetry.system_telemetry(metric)          # type: ignore[arg-type]
    assert result["status"] == "success"
    assert result["metric_or_action"] == metric
    assert expected_key in result["payload"]


def test_unknown_metric_is_rejected():
    result = telemetry.system_telemetry("temperature")   # type: ignore[arg-type]
    assert result["status"] == "error"
    assert "allowed" in result["payload"]


def test_machine_health_reports_a_verdict():
    result = telemetry.machine_health()
    payload = result["payload"]
    assert result["status"] == "success"
    assert payload["severity"] in {"ok", "warning", "critical"}
    assert isinstance(payload["issues"], list)
    assert payload["verdict"] in result["summary"] or result["summary"]
    assert payload["uptime_hours"] >= 0


def test_machine_health_flags_memory_pressure(monkeypatch):
    fake = psutil.virtual_memory()._replace(percent=96, used=10, available=1, total=11)
    monkeypatch.setattr(telemetry.psutil, "virtual_memory", lambda: fake)
    result = telemetry.machine_health()
    assert result["payload"]["severity"] == "critical"
    assert any(issue["what"] == "memory" for issue in result["payload"]["issues"])
    assert "attention" in result["summary"].lower()


def test_top_processes_respects_limit_and_sort():
    result = telemetry.top_processes(limit=3, sort="cpu")
    assert result["status"] == "success"
    assert len(result["payload"]["processes"]) <= 3
    assert result["payload"]["sorted_by"] == "cpu"


def test_disk_inventory_lists_volumes():
    result = telemetry.disk_inventory()
    assert result["status"] == "success"
    for volume in result["payload"]["volumes"]:
        assert 0 <= volume["usage_percent"] <= 100
        assert volume["mountpoint"]


def test_network_status_is_measurement_only():
    result = telemetry.network_status()
    assert result["status"] == "success"
    assert "never sends packets" in result["payload"]["note"]
    for interface in result["payload"]["interfaces"]:
        assert "rx_rate_kbps" in interface


def test_gpu_status_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(telemetry.shutil, "which", lambda _name: None)
    result = telemetry.gpu_status()
    assert result["status"] == "unsupported"
    assert result["payload"]["hint"]


def test_gpu_status_parses_nvidia_smi(monkeypatch):
    class Proc:
        returncode = 0
        stdout = "NVIDIA GeForce GTX 1650, 4096, 1024, 37, 52\n"

    monkeypatch.setattr(telemetry.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: Proc())
    result = telemetry.gpu_status()
    assert result["status"] == "success"
    assert result["payload"]["gpus"][0]["name"].startswith("NVIDIA")
    assert result["payload"]["gpus"][0]["utilisation_percent"] == "37"
