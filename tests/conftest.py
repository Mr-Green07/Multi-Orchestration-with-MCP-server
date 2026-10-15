"""
Shared pytest fixtures + import path setup.

Adds the project root to sys.path so tests can `import security`, `import tools`,
etc., and provides small helpers (a scriptable fake model, a fake retriever, and
temporary workspace/db fixtures).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import security  # noqa: E402
from tools import ToolContext  # noqa: E402


# ---------------------------------------------------------------------------
# Fake model: returns scripted strings in order
# ---------------------------------------------------------------------------
class ScriptedModel:
    """A stand-in for the LLM. Returns queued responses; records the messages
    it was called with so tests can inspect the conversation."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        if not self.responses:
            return '{"action": "final", "answer": "no more scripted responses"}'
        return self.responses.pop(0)


class FakeRetriever:
    """Deterministic retriever for document-search tests."""

    def __init__(self, hits=None):
        self.hits = hits if hits is not None else [
            {"source": "guide.txt", "chunk_index": 0, "score": 0.92,
             "text": "The capital of France is Paris."}
        ]

    def search(self, query, top_k=4):
        return self.hits[:top_k]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def ws_subdir():
    """A unique temporary subdirectory inside workspace/, auto-cleaned."""
    name = f"_pytest_{uuid.uuid4().hex[:8]}"
    path = security.WORKSPACE_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    yield name, path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def sample_db(tmp_path):
    """A small read-only-friendly SQLite database on disk."""
    db_file = tmp_path / "sample.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    conn.executemany("INSERT INTO users (name, age) VALUES (?, ?)",
                     [("Alice", 30), ("Bob", 25), ("Carol", 41)])
    conn.commit()
    conn.close()
    return str(db_file)


@pytest.fixture
def ctx(sample_db):
    """A ToolContext with confirm=True and the sample DB attached."""
    return ToolContext(confirm=lambda _msg: True, db_path=sample_db,
                       logger=security.get_logger("test"))
