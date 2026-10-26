"""mcp_server/tools/knowledge.py
=============================
Persistence for the agent itself:

* **memory** - "remember that my project lives in D:/work" survives restarts;
* **profiles** - named multi-step routines ("work setup") that the CLI can run;
* **document search** - ask-my-files retrieval over the workspace jail.

The document index is deliberately dependency-free: a term-frequency score with a
filename boost, rebuilt lazily and invalidated by the newest mtime in the jail.
That keeps the project installable with no FAISS/sentence-transformers stack while
still answering "where did I write about X?".
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import config
from mcp_server.tools._common import iter_jail_files, resolve_in_jail, respond

_TOKEN = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were",
    "for", "on", "at", "by", "with", "from", "that", "this", "it", "as", "be",
    "what", "which", "who", "how", "why", "where", "my", "me", "i", "you",
})


# --------------------------------------------------------------------------- database
def _db_path() -> Path:
    Path(config.DATABASE_DIR).mkdir(parents=True, exist_ok=True)
    return Path(config.MEMORY_DB_PATH)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory (
               key TEXT PRIMARY KEY,
               value TEXT NOT NULL,
               tags TEXT DEFAULT '',
               created_at REAL NOT NULL,
               updated_at REAL NOT NULL,
               deleted INTEGER DEFAULT 0
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS profile (
               name TEXT PRIMARY KEY,
               description TEXT DEFAULT '',
               steps TEXT NOT NULL,
               created_at REAL NOT NULL
           )"""
    )
    return conn


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOPWORDS]


# --------------------------------------------------------------------------- memory
def remember(key: str, value: str, tags: str = "",
             correlation_id: str | None = None) -> dict:
    key = (key or "").strip()
    if not key or value is None:
        return respond(tool="remember", action="remember", status="error",
                       summary="Both 'key' and 'value' are required.",
                       payload={"code": "missing_fields"}, correlation_id=correlation_id)
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO memory(key, value, tags, created_at, updated_at, deleted)
               VALUES (?,?,?,?,?,0)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value, tags=excluded.tags,
                   updated_at=excluded.updated_at, deleted=0""",
            (key, str(value), tags, now, now),
        )
    return respond(tool="remember", action="remember", status="success",
                   summary=f"Remembered '{key}'.",
                   payload={"key": key, "value": str(value)[:500]},
                   correlation_id=correlation_id, applied=True)


def recall(query: str | None = None, key: str | None = None,
           limit: int = 5, correlation_id: str | None = None) -> dict:
    with _connect() as conn:
        if key:
            rows = conn.execute(
                "SELECT key, value, tags, updated_at FROM memory "
                "WHERE key = ? AND deleted = 0", (key,)).fetchall()
        elif query:
            like = f"%{query.lower()}%"
            rows = conn.execute(
                """SELECT key, value, tags, updated_at FROM memory
                   WHERE deleted = 0 AND (LOWER(key) LIKE ? OR LOWER(value) LIKE ?
                                          OR LOWER(tags) LIKE ?)
                   ORDER BY updated_at DESC LIMIT ?""",
                (like, like, like, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, value, tags, updated_at FROM memory WHERE deleted = 0 "
                "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    entries = [{"key": r["key"], "value": r["value"], "tags": r["tags"],
                "updated_epoch": int(r["updated_at"])} for r in rows]
    if not entries:
        return respond(tool="recall", action="recall", status="success",
                       summary="Nothing stored matches that.",
                       payload={"entries": []}, correlation_id=correlation_id)
    return respond(tool="recall", action="recall", status="success",
                   summary=f"Found {len(entries)} memory entr"
                           f"{'y' if len(entries) == 1 else 'ies'}.",
                   payload={"entries": entries}, correlation_id=correlation_id)


def forget(key: str, correlation_id: str | None = None) -> dict:
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE memory SET deleted = 1 WHERE key = ? AND deleted = 0", (key,))
    if cursor.rowcount == 0:
        return respond(tool="forget", action="forget", status="error",
                       summary=f"No memory entry named '{key}'.",
                       payload={"code": "not_found"}, correlation_id=correlation_id)
    return respond(tool="forget", action="forget", status="success",
                   summary=f"Forgot '{key}' (soft delete; the row is retained).",
                   payload={"key": key}, correlation_id=correlation_id, applied=True)


# --------------------------------------------------------------------------- profiles
def save_profile(name: str, steps: Iterable[dict], description: str = "",
                 correlation_id: str | None = None) -> dict:
    name = (name or "").strip().lower()
    steps = list(steps or [])
    if not name or not steps:
        return respond(tool="save_profile", action="save_profile", status="error",
                       summary="A profile needs a name and at least one step.",
                       payload={"code": "missing_fields"}, correlation_id=correlation_id)
    for step in steps:
        if "tool" not in step or "arguments" not in step:
            return respond(tool="save_profile", action="save_profile", status="error",
                           summary="Each step must contain 'tool' and 'arguments'.",
                           payload={"code": "bad_step", "step": step},
                           correlation_id=correlation_id)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO profile(name, description, steps, created_at)
               VALUES (?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                   description=excluded.description, steps=excluded.steps""",
            (name, description, json.dumps(steps), time.time()),
        )
    return respond(tool="save_profile", action="save_profile", status="success",
                   summary=f"Saved profile '{name}' with {len(steps)} step(s).",
                   payload={"name": name, "steps": steps},
                   correlation_id=correlation_id, applied=True)


def list_profiles(correlation_id: str | None = None) -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name, description, steps, created_at FROM profile ORDER BY name"
        ).fetchall()
    profiles = [{"name": r["name"], "description": r["description"],
                 "steps": json.loads(r["steps"]), "created_at": int(r["created_at"])}
                for r in rows]
    return respond(tool="list_profiles", action="list_profiles", status="success",
                   summary=f"{len(profiles)} profile(s) stored.",
                   payload={"profiles": profiles}, correlation_id=correlation_id)


def get_profile(name: str, correlation_id: str | None = None) -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT name, description, steps FROM profile WHERE name = ?",
                           ((name or "").lower(),)).fetchone()
    if not row:
        return respond(tool="get_profile", action="get_profile", status="error",
                       summary=f"No profile named '{name}'.",
                       payload={"code": "not_found"}, correlation_id=correlation_id)
    return respond(tool="get_profile", action="get_profile", status="success",
                   summary=f"Profile '{row['name']}' has {len(json.loads(row['steps']))} step(s).",
                   payload={"name": row["name"], "description": row["description"],
                            "steps": json.loads(row["steps"])},
                   correlation_id=correlation_id)


# --------------------------------------------------------------------------- documents
_INDEX_CACHE: dict[str, Any] = {"signature": None, "docs": []}


def _jail_signature(root: Path) -> tuple[int, int]:
    newest = 0.0
    count = 0
    for path in iter_jail_files(root, limit=config.MAX_SEARCH_FILES):
        count += 1
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return (count, int(newest))


def _build_index(root: Path) -> list[dict[str, Any]]:
    signature = _jail_signature(root)
    if _INDEX_CACHE["signature"] == signature:
        return list(_INDEX_CACHE["docs"])
    docs: list[dict[str, Any]] = []
    for path in iter_jail_files(root, limit=config.MAX_SEARCH_FILES):
        try:
            if path.stat().st_size > config.MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        docs.append({
            "path": path.relative_to(root).as_posix(),
            "name": path.name,
            "text": text[:200_000],
            "tokens": _tokens(text),
        })
    _INDEX_CACHE.update(signature=signature, docs=docs)
    return docs


def _snippet(text: str, terms: list[str], width: int = 220) -> str:
    lowered = text.lower()
    for term in terms:
        position = lowered.find(term)
        if position >= 0:
            start = max(0, position - width // 3)
            return " ".join(text[start:start + width].split())
    return " ".join(text[:width].split())


def search_documents(query: str, top_k: int = 5, relative_path: str = "",
                     correlation_id: str | None = None) -> dict:
    """Rank workspace documents against a query and return cited snippets."""
    if not (query or "").strip():
        return respond(tool="search_documents", action="search_documents", status="error",
                       summary="A non-empty query is required.",
                       payload={"code": "missing_query"}, correlation_id=correlation_id)

    try:
        root = resolve_in_jail(relative_path)
    except Exception as exc:
        return respond(tool="search_documents", action="search_documents", status="error",
                       summary=str(exc), payload={"code": "jail_violation"},
                       correlation_id=correlation_id)
    if not root.is_dir():
        root = root.parent

    terms = _tokens(query)
    if not terms:
        return respond(tool="search_documents", action="search_documents", status="success",
                       summary="The query contained only stop words; nothing to search for.",
                       payload={"matches": []}, correlation_id=correlation_id)

    docs = _build_index(root)
    scored = []
    for doc in docs:
        counts: dict[str, float] = {}
        for term in terms:
            exact = doc["tokens"].count(term)
            if exact:
                counts[term] = float(exact)
            else:
                # tolerate morphology: "deploy" should reach "deployment"
                near = sum(1 for token in doc["tokens"]
                           if token.startswith(term) or term.startswith(token))
                if near:
                    counts[term] = round(near * 0.5, 2)
        score = sum(counts.values())
        if score == 0:
            continue
        filename_boost = sum(2 for term in terms if term in doc["name"].lower())
        scored.append({
            "source": doc["path"],
            "score": round(score + filename_boost, 3),
            "term_hits": {k: v for k, v in counts.items() if v},
            "snippet": _snippet(doc["text"], terms),
        })
    scored.sort(key=lambda r: (-r["score"], r["source"]))
    top = scored[: max(1, min(top_k, 10))]

    if not top:
        return respond(tool="search_documents", action="search_documents", status="success",
                       summary=f"No workspace document mentions {', '.join(terms[:4])}.",
                       payload={"matches": [], "documents_indexed": len(docs)},
                       correlation_id=correlation_id)
    return respond(
        tool="search_documents", action="search_documents", status="success",
        summary=f"Found {len(top)} relevant document(s) of {len(docs)} indexed.",
        payload={"query": query, "matches": top, "documents_indexed": len(docs),
                 "method": "term frequency with filename boost"},
        correlation_id=correlation_id,
    )


def index_status(correlation_id: str | None = None) -> dict:
    try:
        root = resolve_in_jail("")
        docs = _build_index(root)
    except Exception as exc:
        return respond(tool="index_status", action="index_status", status="error",
                       summary=f"Index unavailable: {exc}", payload={},
                       correlation_id=correlation_id)
    return respond(tool="index_status", action="index_status", status="success",
                   summary=f"{len(docs)} document(s) indexed in the workspace.",
                   payload={"documents": len(docs),
                            "paths": [d["path"] for d in docs[:20]],
                            "root": str(root)},
                   correlation_id=correlation_id)
