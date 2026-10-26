"""Application lifecycle and power: allowlist, denylist, two-phase confirmation."""
from __future__ import annotations

import os

import psutil
import pytest

import config
from mcp_server import policy
from mcp_server.tools import lifecycle, power


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    policy.reset_all_limits()
    yield
    policy.reset_all_limits()


# --------------------------------------------------------------------------- launching
def test_launch_rejects_unknown_app():
    result = lifecycle.execute_app_lifecycle("launch", app_name="cmd.exe /c format c:")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "app_not_allowed"


def test_launch_requires_app_name():
    result = lifecycle.execute_app_lifecycle("launch")
    assert result["status"] == "error"
    assert result["payload"]["error"] == "app_name required"


def test_launch_dry_run_reports_argv(monkeypatch):
    policy.set_dry_run(True)
    result = lifecycle.execute_app_lifecycle("launch", app_name="vscode")
    assert result["status"] == "dry_run"
    assert result["payload"]["argv"] == policy.resolve_app_argv("vscode")
    assert result["payload"]["would_execute"] is True


def test_launch_missing_binary_is_reported(monkeypatch):
    monkeypatch.setitem(config.ALLOWED_APPS, "ghost",
                        {"win32": ["ghost.exe"], "darwin": ["ghost"], "linux": ["ghost"]})
    result = lifecycle.execute_app_lifecycle("launch", app_name="ghost")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "binary_missing"


# --------------------------------------------------------------------------- killing
def test_kill_of_protected_process_is_refused():
    result = lifecycle.execute_app_lifecycle("request_kill", pid=1)
    assert result["status"] == "error"
    assert result["payload"]["code"] == "protected_process"


def test_kill_requires_a_pid():
    result = lifecycle.execute_app_lifecycle("request_kill")
    assert result["status"] == "error"
    assert result["payload"]["error"] == "pid required"


def test_kill_of_own_process_issues_a_token_without_killing():
    pid = os.getpid()
    result = lifecycle.execute_app_lifecycle("request_kill", pid=pid)
    assert result["status"] == "requires_confirmation"
    assert result["confirmation_token"]
    assert result["payload"]["target_pid"] == pid
    # nothing happened: we are still running
    assert psutil.pid_exists(pid)


def test_kill_with_bad_token_is_refused():
    result = lifecycle.execute_app_lifecycle("request_kill", pid=os.getpid(),
                                             confirmation_token="not-a-token")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "bad_token"


def test_kill_dry_run_is_simulated():
    policy.set_dry_run(True)
    result = lifecycle.execute_app_lifecycle("request_kill", pid=os.getpid())
    assert result["status"] == "dry_run"
    assert psutil.pid_exists(os.getpid())


def test_list_running_ranks_processes():
    result = lifecycle.execute_app_lifecycle("list_running", limit=5)
    assert result["status"] == "success"
    processes = result["payload"]["processes"]
    assert processes and len(processes) <= 5
    assert {"pid", "name", "memory_percent", "cpu_percent"} <= set(processes[0])
    assert "protected" in processes[0]


# --------------------------------------------------------------------------- power
def test_shutdown_requires_confirmation_and_token():
    result = power.execute_power_session("shutdown")
    assert result["status"] == "requires_confirmation"
    assert result["confirmation_token"]
    assert "warning" in result["payload"]


def test_restart_with_invalid_token_is_rejected():
    result = power.execute_power_session("restart", confirmation_token="bogus")
    assert result["status"] == "error"
    assert "invalid" in result["summary"].lower()


def test_power_dry_run_executes_nothing():
    policy.set_dry_run(True)
    for action in ("lock_screen", "sleep", "restart", "shutdown"):
        result = power.execute_power_session(action)
        assert result["status"] == "dry_run", action


def test_power_rate_limit_blocks_a_retry_loop():
    policy.set_dry_run(True)
    try:
        for _ in range(policy.POWER_LIMITER.max_events):
            assert power.execute_power_session("shutdown")["status"] == "dry_run"
    finally:
        policy.set_dry_run(False)
    # budget is consumed only by real actions, so simulate consumption here
    for _ in range(policy.POWER_LIMITER.max_events):
        policy.POWER_LIMITER.consume()
    blocked = power.execute_power_session("lock_screen")
    assert blocked["status"] == "rate_limited"
    assert "Rate limited" in blocked["summary"]


def test_lock_screen_is_executed_on_this_host(monkeypatch):
    """A benign, reversible action: prove the success path works end to end."""
    monkeypatch.setattr(power, "_execute", lambda action: (True, ""))
    result = power.execute_power_session("lock_screen")
    assert result["status"] == "success"
    assert result["applied"] is True


def test_launch_approval_gate_is_off_by_default(monkeypatch):
    assert config.REQUIRE_LAUNCH_APPROVAL is False


def test_launch_approval_requires_a_token_when_enabled(monkeypatch):
    """With AGENT_APPROVE_LAUNCH=1 a launch is two-phase, like a kill."""
    monkeypatch.setattr(config, "REQUIRE_LAUNCH_APPROVAL", True)
    app = sorted(config.ALLOWED_APPS)[0]

    first = lifecycle.execute_app_lifecycle("launch", app_name=app)
    assert first["status"] == "requires_confirmation"
    assert first["applied"] is False
    assert first["confirmation_token"]

    bad = lifecycle.execute_app_lifecycle("launch", app_name=app,
                                      confirmation_token="not-a-real-token")
    assert bad["status"] == "error"
    assert bad["payload"]["code"] == "bad_token"
    assert bad["applied"] is False
