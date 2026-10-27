"""Workspace tool: jail containment, caps, search, overwrite protection."""
from __future__ import annotations

import pytest

import config
from mcp_server import policy
from mcp_server.tools import workspace
from mcp_server.tools._common import JailViolation, resolve_in_jail


@pytest.fixture
def jail(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_JAIL_ROOT", tmp_path)
    monkeypatch.setattr(config, "DRY_RUN", False)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "todo.md").write_text("buy milk\ncall the bank\n", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "big.log").write_text("x" * 5000, encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n")
    return tmp_path


# --------------------------------------------------------------------------- containment
@pytest.mark.parametrize("path", [
    "../outside.txt", "../../etc/passwd", "/etc/passwd", "C:\\Windows\\win.ini",
    "\\\\server\\share\\file", "notes/../../escape", "file:///etc/passwd",
])
def test_traversal_is_rejected(jail, path):
    with pytest.raises(JailViolation):
        resolve_in_jail(path)


def test_dot_and_empty_resolve_to_the_root(jail):
    assert resolve_in_jail("") == jail.resolve()
    assert resolve_in_jail(".") == jail.resolve()


def test_list_action(jail):
    result = workspace.execute_workspace_fs("list")
    assert result["status"] == "success"
    names = {item["name"] for item in result["payload"]["items"]}
    assert {"notes", "readme.txt"} <= names


def test_list_of_unknown_path_is_an_error(jail):
    result = workspace.execute_workspace_fs("list", relative_path="nope")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "not_found"


def test_traversal_message_says_forbidden(jail):
    result = workspace.execute_workspace_fs("read_text", relative_path="../../etc/passwd")
    assert result["status"] == "error"
    assert "forbidden" in result["summary"].lower()


# --------------------------------------------------------------------------- reading
def test_read_text(jail):
    result = workspace.execute_workspace_fs("read_text", relative_path="notes/todo.md")
    assert result["status"] == "success"
    assert "buy milk" in result["payload"]["content"]
    assert result["payload"]["truncated"] is False


def test_read_refuses_binary_extension(jail):
    result = workspace.execute_workspace_fs("read_text", relative_path="image.png")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "not_text"


def test_read_truncates_long_text(jail, monkeypatch):
    monkeypatch.setattr(config, "MAX_READ_CHARS", 100)
    result = workspace.execute_workspace_fs("read_text", relative_path="big.log")
    assert result["status"] == "success"
    assert result["payload"]["truncated"] is True
    assert len(result["payload"]["content"]) == 100


def test_stat(jail):
    result = workspace.execute_workspace_fs("stat", relative_path="readme.txt")
    assert result["payload"]["type"] == "file"
    assert result["payload"]["size_bytes"] == len("hello world\n")


# --------------------------------------------------------------------------- search
def test_search_finds_matches_with_line_numbers(jail):
    result = workspace.execute_workspace_fs("search", search_query="bank")
    assert result["status"] == "success"
    matches = result["payload"]["matches"]
    assert matches and matches[0]["path"] == "notes/todo.md"
    assert matches[0]["line"] == 2


def test_search_requires_a_query(jail):
    result = workspace.execute_workspace_fs("search")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "missing_query"


def test_search_is_capped(jail, monkeypatch):
    monkeypatch.setattr(config, "MAX_SEARCH_MATCHES", 1)
    for index in range(4):
        (jail / f"note{index}.txt").write_text("needle\n", encoding="utf-8")
    result = workspace.execute_workspace_fs("search", search_query="needle")
    assert len(result["payload"]["matches"]) == 1
    assert result["payload"]["truncated"] is True


# --------------------------------------------------------------------------- writing
def test_write_creates_a_file(jail):
    result = workspace.execute_workspace_fs(
        "write_text", relative_path="notes/new.md", content="fresh")
    assert result["status"] == "success"
    assert (jail / "notes" / "new.md").read_text(encoding="utf-8") == "fresh"


def test_write_cannot_escape_the_jail(jail):
    result = workspace.execute_workspace_fs(
        "write_text", relative_path="../evil.sh", content="rm -rf /")
    assert result["status"] == "error"
    assert not (jail.parent / "evil.sh").exists()


def test_overwrite_requires_a_confirmation_token(jail):
    first = workspace.execute_workspace_fs(
        "write_text", relative_path="readme.txt", content="replacement")
    assert first["status"] == "requires_confirmation"
    assert first["confirmation_token"]
    assert (jail / "readme.txt").read_text(encoding="utf-8") == "hello world\n"

    second = workspace.execute_workspace_fs(
        "write_text", relative_path="readme.txt", content="replacement",
        confirmation_token=first["confirmation_token"])
    assert second["status"] == "success"
    assert (jail / "readme.txt").read_text(encoding="utf-8") == "replacement"


def test_write_dry_run_changes_nothing(jail):
    policy.set_dry_run(True)
    try:
        result = workspace.execute_workspace_fs(
            "write_text", relative_path="dry.txt", content="nope")
    finally:
        policy.set_dry_run(False)
    assert result["status"] == "dry_run"
    assert not (jail / "dry.txt").exists()


def test_tree_renders_nested_entries(jail):
    result = workspace.execute_workspace_fs("tree")
    assert result["status"] == "success"
    assert any("todo.md" in line for line in result["payload"]["tree"])


def test_unknown_action_is_rejected(jail):
    result = workspace.execute_workspace_fs("delete", relative_path="readme.txt")  # type: ignore[arg-type]
    assert result["status"] == "error"
    assert result["payload"]["code"] == "invalid_action"


# --------------------------------------------------------------------- read-only scopes
def test_scopes_are_absent_by_default(jail):
    result = workspace.execute_workspace_fs("list", relative_path="@scopes")
    assert result["status"] == "success"
    assert result["payload"]["scopes"] == []


def test_scopes_enable_reads_outside_the_jail_but_never_writes(jail, monkeypatch,
                                                               tmp_path):
    outside = tmp_path / "Downloads"
    outside.mkdir()
    (outside / "note.md").write_text("outside the jail", encoding="utf-8")
    monkeypatch.setattr(config, "READ_ONLY_ROOTS", (outside,))

    listing = workspace.execute_workspace_fs("list", relative_path="@scopes")
    assert listing["payload"]["scopes"][0]["name"] == "@Downloads"

    read = workspace.execute_workspace_fs("read_text",
                                         relative_path="@Downloads/note.md")
    assert read["status"] == "success"
    assert read["payload"]["content"] == "outside the jail"
    assert read["payload"]["writable"] is False

    refused = workspace.execute_workspace_fs("write_text",
                                            relative_path="@Downloads/new.md",
                                            content="nope")
    assert refused["status"] == "error"
    assert refused["payload"]["code"] == "scope_read_only"
    assert not (outside / "new.md").exists()


def test_scopes_block_traversal_and_unknown_names(jail, monkeypatch, tmp_path):
    outside = tmp_path / "Downloads"
    outside.mkdir()
    monkeypatch.setattr(config, "READ_ONLY_ROOTS", (outside,))
    traversal = workspace.execute_workspace_fs("read_text",
                                               relative_path="@Downloads/../../etc/passwd")
    assert traversal["status"] == "error"
    assert traversal["payload"]["code"] == "scope_violation"

    unknown = workspace.execute_workspace_fs("read_text", relative_path="@Nope/x.txt")
    assert unknown["status"] == "error"
    assert unknown["payload"]["code"] == "scope_violation"
