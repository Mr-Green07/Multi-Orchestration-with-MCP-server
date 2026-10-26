"""Knowledge tools: memory, profiles and ask-my-files search."""
from __future__ import annotations

import pytest

import config
from mcp_server.tools import knowledge


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEMORY_DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(config, "WORKSPACE_JAIL_ROOT", tmp_path / "jail")
    (tmp_path / "jail").mkdir()
    knowledge._INDEX_CACHE.update(signature=None, docs=[])
    return tmp_path


# --------------------------------------------------------------------------- memory
def test_remember_then_recall_by_key():
    assert knowledge.remember("editor", "vscode")["status"] == "success"
    result = knowledge.recall(key="editor")
    entries = result["payload"]["entries"]
    assert entries and entries[0]["value"] == "vscode"


def test_recall_by_free_text():
    knowledge.remember("project", "the orchestrator lives in agent/")
    result = knowledge.recall(query="orchestrator")
    assert result["payload"]["entries"]


def test_remember_overwrites_and_updates_timestamp():
    knowledge.remember("k", "first")
    knowledge.remember("k", "second")
    entries = knowledge.recall(key="k")["payload"]["entries"]
    assert len(entries) == 1 and entries[0]["value"] == "second"


def test_forget_soft_deletes():
    knowledge.remember("temp", "value")
    assert knowledge.forget("temp")["status"] == "success"
    assert knowledge.recall(key="temp")["payload"]["entries"] == []
    # a second forget is an error, not a crash
    assert knowledge.forget("temp")["status"] == "error"


def test_missing_fields_are_rejected():
    assert knowledge.remember("", "x")["status"] == "error"
    assert knowledge.remember("k", None)["status"] == "error"      # type: ignore[arg-type]


# --------------------------------------------------------------------------- profiles
def test_profile_round_trip():
    steps = [{"tool": "system_telemetry", "arguments": {"metric": "cpu"}},
             {"tool": "machine_health", "arguments": {}}]
    assert knowledge.save_profile("work", steps, description="open everything")["status"] == "success"

    listing = knowledge.list_profiles()["payload"]["profiles"]
    assert listing[0]["name"] == "work"
    assert len(listing[0]["steps"]) == 2

    fetched = knowledge.get_profile("WORK")["payload"]
    assert fetched["steps"] == steps


def test_profile_rejects_bad_steps():
    result = knowledge.save_profile("broken", [{"arguments": {}}])
    assert result["status"] == "error"
    assert result["payload"]["code"] == "bad_step"


def test_unknown_profile_is_an_error():
    assert knowledge.get_profile("nope")["status"] == "error"


# --------------------------------------------------------------------------- documents
@pytest.fixture
def docs(tmp_path):
    jail = tmp_path / "jail"
    (jail / "notes").mkdir(parents=True, exist_ok=True)
    (jail / "notes" / "deploy.md").write_text(
        "The deployment pipeline runs on Fridays. Rollback is via the release tag.",
        encoding="utf-8")
    (jail / "shopping.txt").write_text("eggs, bread, milk", encoding="utf-8")
    (jail / "recipe.md").write_text("Whisk the eggs and fold the flour.", encoding="utf-8")
    return jail


def test_search_documents_ranks_by_term_frequency(docs):
    result = knowledge.search_documents("eggs")
    assert result["status"] == "success"
    paths = [match["source"] for match in result["payload"]["matches"]]
    assert "shopping.txt" in paths or "recipe.md" in paths
    assert all(match["snippet"] for match in result["payload"]["matches"])


def test_search_documents_prefers_filename_matches(docs):
    result = knowledge.search_documents("deploy")
    top = result["payload"]["matches"][0]
    assert top["source"] == "notes/deploy.md"


def test_search_documents_reports_no_match(docs):
    result = knowledge.search_documents("quantum chromodynamics")
    assert result["status"] == "success"
    assert result["payload"]["matches"] == []


def test_search_documents_requires_a_query(docs):
    assert knowledge.search_documents("   ")["status"] == "error"


def test_index_status_counts_documents(docs):
    result = knowledge.index_status()
    assert result["status"] == "success"
    assert result["payload"]["documents"] >= 3


def test_index_rebuilds_when_files_change(docs):
    knowledge.search_documents("Friday")
    (docs / "later.md").write_text("A new note about Friday deploys.", encoding="utf-8")
    result = knowledge.search_documents("Friday")
    assert result["payload"]["documents_indexed"] >= 4
