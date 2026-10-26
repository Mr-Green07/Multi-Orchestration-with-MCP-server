"""Retrieval (ask-my-files) tests.

The original suite imported ``old_directory.retrieval``, a package that no longer
exists. The retrieval capability now lives in ``mcp_server.tools.knowledge`` and
needs no FAISS or sentence-transformers, so these tests always run.
"""
from __future__ import annotations

import pytest

import config
from mcp_server.tools import knowledge


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_JAIL_ROOT", tmp_path)
    knowledge._INDEX_CACHE.update(signature=None, docs=[])
    (tmp_path / "guide.md").write_text(
        "Deployment guide. The release train leaves on Friday and rollback uses tags.",
        encoding="utf-8")
    (tmp_path / "notes.txt").write_text("Groceries: eggs, milk, flour.", encoding="utf-8")
    return tmp_path


def test_tokeniser_drops_stopwords():
    tokens = knowledge._tokens("What is the deployment window?")
    assert "deployment" in tokens and "the" not in tokens


def test_search_finds_the_right_document():
    result = knowledge.search_documents("rollback")
    assert result["status"] == "success"
    assert result["payload"]["matches"][0]["source"] == "guide.md"


def test_snippet_contains_the_query_context():
    result = knowledge.search_documents("Friday")
    snippet = result["payload"]["matches"][0]["snippet"]
    assert "Friday" in snippet


def test_search_is_bounded_by_top_k():
    result = knowledge.search_documents("the", top_k=1)
    assert len(result["payload"]["matches"]) <= 1


def test_index_cache_reuses_results():
    first = knowledge.index_status()["payload"]["documents"]
    second = knowledge.index_status()["payload"]["documents"]
    assert first == second


def test_missing_query_is_rejected():
    assert knowledge.search_documents("")["status"] == "error"


def test_search_inside_a_subdirectory(workspace):
    (workspace / "sub").mkdir()
    (workspace / "sub" / "deep.md").write_text("A deep note about turbines.", encoding="utf-8")
    result = knowledge.search_documents("turbines", relative_path="sub")
    assert result["payload"]["matches"][0]["source"] == "deep.md"
