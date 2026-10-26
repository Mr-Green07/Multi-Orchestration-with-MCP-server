"""Audit trail: records, correlation, truncation, resilience."""
from __future__ import annotations

import json

import pytest

import config
from mcp_server import audit


@pytest.fixture
def audit_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(config, "AUDIT_ENABLED", True)
    return tmp_path


def test_record_writes_one_json_line(audit_dir):
    entry = audit.record("unit_test", note="hello")
    path = audit.current_log_path()
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "unit_test"
    assert entry["note"] == "hello"
    assert "ts" in entry and "pid" in entry


def test_long_values_are_truncated(audit_dir):
    audit.record("truncate", blob="x" * 2000)
    line = audit.current_log_path().read_text(encoding="utf-8").strip()
    assert len(line) < 1200


def test_tail_returns_latest_records(audit_dir):
    for index in range(5):
        audit.record("tick", index=index)
    records = audit.tail(3)
    assert [r["index"] for r in records] == [2, 3, 4]


def test_correlation_id_is_attached(audit_dir):
    token = audit.set_correlation("abc-123")
    try:
        audit.tool_event(tool="demo", status="success", summary="did a thing")
    finally:
        audit.reset_correlation(token)
    record = audit.tail(1)[0]
    assert record["correlation_id"] == "abc-123"
    assert record["tool"] == "demo"


def test_audit_disabled_writes_nothing(audit_dir, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_ENABLED", False)
    audit.record("should_not_exist")
    assert audit.current_log_path().exists() is False


def test_audit_failure_never_raises(audit_dir, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DIR", audit_dir / "file_not_dir")
    (audit_dir / "file_not_dir").write_text("i am a file", encoding="utf-8")
    entry = audit.record("resilient")
    assert entry["event"] == "resilient"


def test_new_correlation_ids_are_unique():
    ids = {audit.new_correlation_id() for _ in range(50)}
    assert len(ids) == 50
