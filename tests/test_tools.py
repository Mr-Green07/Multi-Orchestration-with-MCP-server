"""Unit tests: tool validation, calculator tool, file tools, sqlite tool, report."""

import pytest

import security as security
import tools as tools
from tools import ToolContext, ToolError, run_tool, validate_arguments


# --------------------------- argument validation ---------------------------
def test_validate_arguments_ok():
    schema = {"expression": {"type": "string", "required": True}}
    assert validate_arguments(schema, {"expression": "2+2"}) == {"expression": "2+2"}


def test_validate_arguments_missing_required():
    schema = {"path": {"type": "string", "required": True}}
    with pytest.raises(ToolError):
        validate_arguments(schema, {})


def test_validate_arguments_wrong_type():
    schema = {"top_k": {"type": "integer", "required": False, "default": 4}}
    with pytest.raises(ToolError):
        validate_arguments(schema, {"top_k": "five"})


def test_validate_arguments_defaults():
    schema = {"subdir": {"type": "string", "required": False, "default": "."}}
    assert validate_arguments(schema, {}) == {"subdir": "."}


# --------------------------- calculate tool ---------------------------
def test_calculate_tool():
    res = run_tool("calculate", {"expression": "25 * 4"}, ToolContext())
    assert res["ok"] is True
    assert res["result"]["value"] == 100


def test_calculate_tool_rejects_code():
    res = run_tool("calculate", {"expression": "__import__('os').system('ls')"}, ToolContext())
    assert res["ok"] is False


# --------------------------- unknown tool / bad args --------------------------
def test_unknown_tool():
    res = run_tool("hack_the_planet", {}, ToolContext())
    assert res["ok"] is False
    assert "Unknown tool" in res["error"]


def test_missing_argument_via_run_tool():
    res = run_tool("read_text_file", {}, ToolContext())
    assert res["ok"] is False
    assert "Missing required argument" in res["error"]


# --------------------------- file tools ---------------------------
def test_list_and_read_files(ws_subdir):
    name, path = ws_subdir
    (path / "hello.txt").write_text("hello world", encoding="utf-8")
    (path / "notes.md").write_text("# title", encoding="utf-8")

    listed = run_tool("list_files", {"subdir": name}, ToolContext())
    assert listed["ok"] is True
    names = {e["name"] for e in listed["result"]["entries"]}
    assert {"hello.txt", "notes.md"} <= names

    read = run_tool("read_text_file", {"path": f"{name}/hello.txt"}, ToolContext())
    assert read["ok"] is True
    assert read["result"]["content"] == "hello world"


def test_read_missing_file(ws_subdir):
    name, _ = ws_subdir
    res = run_tool("read_text_file", {"path": f"{name}/nope.txt"}, ToolContext())
    assert res["ok"] is False
    assert "not found" in res["error"].lower()


def test_read_rejects_traversal():
    res = run_tool("read_text_file", {"path": "../security.py"}, ToolContext())
    assert res["ok"] is False
    assert "traversal" in res["error"].lower()


def test_read_rejects_absolute_path():
    res = run_tool("read_text_file", {"path": "/etc/passwd"}, ToolContext())
    assert res["ok"] is False


def test_read_rejects_binary_extension(ws_subdir):
    name, path = ws_subdir
    (path / "blob.bin").write_bytes(b"\x00\x01\x02")
    res = run_tool("read_text_file", {"path": f"{name}/blob.bin"}, ToolContext())
    assert res["ok"] is False


# --------------------------- sqlite tool ---------------------------
def test_sqlite_select(ctx):
    res = run_tool("query_sqlite", {"query": "SELECT name, age FROM users ORDER BY age"}, ctx)
    assert res["ok"] is True
    assert res["result"]["row_count"] == 3
    assert res["result"]["rows"][0]["name"] == "Bob"


def test_sqlite_pragma(ctx):
    res = run_tool("query_sqlite", {"query": "PRAGMA table_info(users)"}, ctx)
    assert res["ok"] is True
    assert res["result"]["row_count"] >= 3


def test_sqlite_rejects_write(ctx):
    res = run_tool("query_sqlite", {"query": "DELETE FROM users"}, ctx)
    assert res["ok"] is False


def test_sqlite_call_limit(ctx):
    ctx.reset_counters()
    ok_count = 0
    for _ in range(security.MAX_SQL_CALLS + 2):
        r = run_tool("query_sqlite", {"query": "SELECT 1"}, ctx)
        ok_count += 1 if r["ok"] else 0
    assert ok_count == security.MAX_SQL_CALLS


# --------------------------- report tool ---------------------------
def test_create_report_and_overwrite_guard():
    fname = "pytest_report.md"
    target = security.WORKSPACE_DIR / fname
    try:
        res = run_tool("create_report",
                       {"filename": fname, "title": "Test", "content": "Body text."},
                       ToolContext(confirm=lambda _m: True))
        assert res["ok"] is True
        assert target.exists()
        assert "Test" in target.read_text(encoding="utf-8")

        # Overwrite denied when confirm returns False.
        denied = run_tool("create_report",
                          {"filename": fname, "content": "new"},
                          ToolContext(confirm=lambda _m: False))
        assert denied["ok"] is False

        # Overwrite allowed when confirmed.
        allowed = run_tool("create_report",
                           {"filename": fname, "content": "new body"},
                           ToolContext(confirm=lambda _m: True))
        assert allowed["ok"] is True
    finally:
        target.unlink(missing_ok=True)


def test_create_report_refuses_path_escape():
    res = run_tool("create_report",
                   {"filename": "../escape.md", "content": "x"},
                   ToolContext(confirm=lambda _m: True))
    # sanitize_filename strips the path, so it still lands safely in workspace/.
    assert res["ok"] is True
    saved = res["result"]["saved_to"]
    assert saved.startswith("workspace/")
    assert ".." not in saved
    (security.WORKSPACE_DIR / "escape.md").unlink(missing_ok=True)
