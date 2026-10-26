"""Policy layer: denylist, launch allowlist, rate limiting, dry-run switch."""
from __future__ import annotations

import pytest

import config
from mcp_server import policy


# --------------------------------------------------------------------------- denylist
@pytest.mark.parametrize("name", [
    "explorer.exe", "EXPLORER.EXE", "lsass.exe", "csrss.exe", "systemd",
    "C:\\\\Windows\\\\System32\\\\winlogon.exe",
])
def test_protected_names_are_recognised(name):
    assert policy.is_protected_name(name) is True


@pytest.mark.parametrize("name", ["notepad.exe", "chrome.exe", "python3", "", None])
def test_ordinary_names_are_not_protected(name):
    assert policy.is_protected_name(name) is False


def test_assert_terminable_rejects_our_own_supervisor():

    with pytest.raises(policy.PolicyError):
        # pid 1 is init/systemd on POSIX and the Windows equivalent name is listed
        policy.assert_terminable(1)


def test_assert_terminable_accepts_a_normal_process():
    import os

    import psutil

    policy.assert_terminable(psutil.Process(os.getpid()).pid, psutil.Process(os.getpid()).name())


# --------------------------------------------------------------------------- allowlist
def test_resolve_app_argv_returns_a_list_for_known_apps():
    argv = policy.resolve_app_argv("vscode")
    assert isinstance(argv, list) and argv


def test_resolve_app_argv_rejects_unknown_and_injection():
    for candidate in ("rm -rf /", "powershell", "", "vscode; rm -rf /"):
        with pytest.raises(policy.PolicyError):
            policy.resolve_app_argv(candidate)


def test_every_allowlisted_app_maps_every_platform():
    for app, mapping in config.ALLOWED_APPS.items():
        assert {"win32", "darwin", "linux"} <= set(mapping), app
        for argv in mapping.values():
            assert isinstance(argv, list) and all(isinstance(part, str) for part in argv)


# --------------------------------------------------------------------------- rate limit
def test_rate_limiter_enforces_window_and_reports_reason():
    limiter = policy.RateLimiter("test", max_events=3, window_seconds=60.0)
    now = 1000.0
    for _ in range(3):
        ok, _reason = limiter.consume(now)
        assert ok
    ok, reason = limiter.check(now)
    assert ok is False and "Rate limited" in reason
    # window slides
    ok, _ = limiter.check(now + 61)
    assert ok is True


def test_rate_limiter_enforces_minimum_gap():
    limiter = policy.RateLimiter("gap", max_events=10, window_seconds=600.0,
                                 min_gap_seconds=30.0)
    assert limiter.consume(50.0)[0] is True
    ok, reason = limiter.check(60.0)
    assert ok is False and "wait" in reason
    assert limiter.check(81.0)[0] is True


def test_rate_limiter_reset():
    limiter = policy.RateLimiter("reset", max_events=1, window_seconds=10.0)
    limiter.consume(0.0)
    assert limiter.check(1.0)[0] is False
    limiter.reset()
    assert limiter.check(1.0)[0] is True


# --------------------------------------------------------------------------- dry run
def test_dry_run_toggle_changes_config(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    policy.set_dry_run(True)
    assert policy.dry_run_enabled() is True
    policy.set_dry_run(False)
    assert policy.dry_run_enabled() is False


# --------------------------------------------------------------------------- elevation
def test_elevation_errors_are_recognised(monkeypatch):
    monkeypatch.setattr(policy, "is_admin", lambda: False)
    for text in ("Access is denied", "permission denied: /dev/backlight",
                 "The requested operation requires elevation",
                 "WinError 5 privilege not held"):
        assert policy.looks_like_elevation_error(text) is True
    assert policy.looks_like_elevation_error("no such device") is False


def test_elevation_refusal_is_structured(monkeypatch):
    monkeypatch.setattr(policy, "is_admin", lambda: False)
    refusal = policy.elevation_refusal("brightness")
    assert refusal["code"] == "needs_elevation"
    assert refusal["retryable"] is False
    assert "brightness" in refusal["message"]
    assert refusal["user_hint"]
