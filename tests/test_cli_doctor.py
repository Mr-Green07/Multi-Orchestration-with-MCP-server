"""CLI helpers and the doctor command."""
from __future__ import annotations

from agent import cli, doctor


# --------------------------------------------------------------------------- formatting
def test_format_result_shows_status_and_summary():
    text = cli.format_result({"status": "success", "summary": "Volume set to 30",
                              "applied": True, "payload": {}})
    assert "[success]" in text and "Volume set to 30" in text
    assert "verified: yes" in text


def test_format_result_surfaces_hints():
    text = cli.format_result({"status": "unsupported", "summary": "no backend",
                              "payload": {"hint": "install xclip"}})
    assert "hint: install xclip" in text


def test_format_agent_result_lists_tool_calls():
    from agent.orchestrator import AgentResult, ToolCall

    result = AgentResult(
        status="ok", answer="done", steps=1,
        tool_calls=[ToolCall(tool="machine_health", arguments={}, status="success",
                             summary="healthy", duration_ms=12.0)],
        correlation_id="abc", dry_run=False,
    )
    text = cli.format_agent_result(result)
    assert "done" in text and "machine_health" in text and "12 ms" in text


def test_help_text_documents_the_slash_commands():
    for command in ("/help", "/health", "/tools", "/undo", "/macro", "/dry", "/log"):
        assert command in cli.HELP


# --------------------------------------------------------------------------- doctor
def test_doctor_checks_cover_the_essentials():
    names = {check.name for check in doctor.run_checks()}
    assert {"python", "workspace jail", "mcp server", "confirmation tokens"} <= names
    assert any(name.startswith("dependency:") for name in names)


def test_doctor_report_is_readable():
    report = doctor.format_checks(doctor.run_checks())
    assert "checks:" in report
    assert "[pass]" in report


def test_doctor_fails_only_on_required_checks():
    checks = [
        doctor.Check("required-missing", False, "gone", required=True),
        doctor.Check("optional-missing", False, "gone", required=False),
    ]
    report = doctor.format_checks(checks)
    assert "1 failure" in report and "1 warning" in report


def test_token_protocol_check_passes():
    assert doctor._check_policy().ok is True


def test_jail_check_is_writable(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "WORKSPACE_JAIL_ROOT", tmp_path / "jail")
    check = doctor._check_jail()
    assert check.ok is True
    assert (tmp_path / "jail").exists()
