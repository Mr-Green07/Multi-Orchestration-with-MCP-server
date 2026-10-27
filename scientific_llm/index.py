"""scientific_llm/index.py
========================
Persistent corpus and index (roadmap item 4).

One SQLite file holds everything the system knows:

* ``documents``   - metadata + raw text, so an answer can always be re-checked;
* ``sections``    - the structural layout of each paper;
* ``chunks``      - the retrievable units, with their section label;
* ``postings``    - an inverted index, term -> (chunk, frequency);
* ``chunk_stats`` - lengths, for BM25;
* ``meta``        - corpus-level statistics and the index format version.

Two retrieval signals are stored side by side, which is what makes the hybrid
retriever in :mod:`scientific_llm.retrieval` possible without any external service:

* **lexical** - real postings, scored by BM25 at query time (no rebuild needed);
* **dense-ish** - a fixed-width hashing embedding per chunk, stored as a compressed
  float blob. A hashing embedding is not a neural encoder, but it is deterministic,
  needs no model download, and captures vocabulary *similarity* that BM25 misses
  (this is the difference between "vector search" and "keyword search"). If a real
  sentence encoder is installed, pass ``embedder=`` and the same column stores its
  vectors instead - nothing else changes.
"""
from __future__ import annotations

import array
import json
import sqlite3
import threading
import zlib
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

import config
from scientific_llm.chunking import ChunkingConfig, chunk_document
from scientific_llm.models import Chunk, DocumentMetadata, ScientificDocument, Section
from scientific_llm.text import sha256_text, terms, tokenize

INDEX_VERSION = "scirag-index-1"
DEFAULT_DB_PATH = Path(config.BASE_DIR) / "database" / "scientific_corpus.db"
DEFAULT_EMBEDDING_DIM = 512

Embedder = Callable[[str], list[float]]


# --------------------------------------------------------------------------- embeddings
def hashing_embedding(text: str, dim: int = DEFAULT_EMBEDDING_DIM) -> list[float]:
    """Signed feature-hashing embedding over tokens and bigrams.

    A token contributes to bucket ``h(token) % dim`` with sign ``h2(token)``; bigrams
    contribute half as much, which preserves a little word order without a model.
    The vector is L2-normalised so cosine similarity is a plain dot product.
    """
    vector = [0.0] * dim
    tokens = terms(text)
    for token in tokens:
        bucket = _stable_hash(token) % dim
        vector[bucket] += 1.0 if _stable_hash(token, salt="sign") % 2 else -1.0
    for left, right in zip(tokens, tokens[1:], strict=False):
        bigram = f"{left}_{right}"
        bucket = _stable_hash(bigram) % dim
        vector[bucket] += 0.5 if _stable_hash(bigram, salt="sign") % 2 else -0.5
    norm = sum(value * value for value in vector) ** 0.5
    if norm:
        return [value / norm for value in vector]
    return vector


def _stable_hash(text: str, salt: str = "") -> int:
    """Deterministic across processes and platforms (unlike ``hash()``)."""
    digest = sha256_text(f"{salt}:{text}")
    return int(digest[:16], 16)


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) != len(right):
        size = min(len(left), len(right))
        left, right = left[:size], right[:size]
    return float(sum(a * b for a, b in zip(left, right, strict=False)))


def _pack(vector: list[float]) -> bytes:
    return zlib.compress(array.array("f", vector).tobytes(), 6)


def _unpack(blob: bytes) -> list[float]:
    floats = array.array("f")
    floats.frombytes(zlib.decompress(blob))
    return list(floats)


# --------------------------------------------------------------------------- index
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    metadata_json TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sections (
    doc_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    heading TEXT NOT NULL,
    level INTEGER NOT NULL,
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (doc_id, ordinal)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    section_heading TEXT NOT NULL,
    section_label TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    starts_mid_sentence INTEGER NOT NULL DEFAULT 0,
    vector BLOB
);
CREATE TABLE IF NOT EXISTS postings (
    term TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    tf INTEGER NOT NULL,
    PRIMARY KEY (term, chunk_id)
);
CREATE TABLE IF NOT EXISTS chunk_stats (
    chunk_id TEXT PRIMARY KEY,
    length INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS postings_term ON postings(term);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
"""


class CorpusIndex:
    """A SQLite-backed corpus with lexical postings and dense vectors."""

    def __init__(self, db_path: str | Path | None = None, *,
                 embedding_dim: int = DEFAULT_EMBEDDING_DIM,
                 embedder: Embedder | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_dim = embedding_dim
        self.embedder: Embedder = embedder or (
            lambda text: hashing_embedding(text, embedding_dim))
        # ``check_same_thread=False`` + a lock around lazy cache fills makes one index
        # usable from the threaded HTTP server. SQLite itself is in serialized mode,
        # which is safe for concurrent reads; the writes below are small and guarded
        # by the connection's own locking.
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('version', ?)",
            (INDEX_VERSION,))
        self.connection.commit()
        self._postings: dict[str, dict[str, int]] | None = None
        self._lengths: dict[str, int] | None = None
        self._vectors: dict[str, list[float]] | None = None
        self._chunk_cache: dict[str, Chunk] = {}

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        try:
            self.connection.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> CorpusIndex:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def reset(self) -> None:
        for table in ("postings", "chunk_stats", "chunks", "sections", "documents", "meta"):
            self.connection.execute(f"DELETE FROM {table}")
        self.connection.commit()
        self.invalidate()

    def invalidate(self) -> None:
        """Drop in-memory caches (called after any write)."""
        self._postings = None
        self._lengths = None
        self._vectors = None
        self._chunk_cache.clear()

    # ------------------------------------------------------------------ writing
    def add_document(self, document: ScientificDocument,
                     config_: ChunkingConfig | None = None) -> dict[str, int]:
        chunks = chunk_document(document, config_)
        existing = self.connection.execute(
            "SELECT sha256 FROM documents WHERE doc_id = ?", (document.doc_id,)
        ).fetchone()
        if existing:
            self.remove_document(document.doc_id)

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.connection.execute(
            "INSERT OR REPLACE INTO documents"
            " (doc_id, title, year, metadata_json, raw_text, sha256, ingested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (document.doc_id, document.metadata.title, document.metadata.year,
             document.metadata.model_dump_json(), document.raw_text,
             document.sha256 or sha256_text(document.raw_text), now))
        self.connection.executemany(
            "INSERT OR REPLACE INTO sections"
            " (doc_id, ordinal, heading, level, label, text) VALUES (?, ?, ?, ?, ?, ?)",
            [(document.doc_id, index, section.heading, section.level, section.label,
              section.text) for index, section in enumerate(document.sections)])

        for chunk in chunks:
            self.connection.execute(
                "INSERT OR REPLACE INTO chunks"
                " (chunk_id, doc_id, section_heading, section_label, ordinal, text,"
                "  token_count, starts_mid_sentence, vector)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk.chunk_id, chunk.doc_id, chunk.section_heading,
                 chunk.section_label, chunk.ordinal, chunk.text, chunk.token_count,
                 int(chunk.starts_mid_sentence), _pack(self.embedder(chunk.text))))
            counts: dict[str, int] = {}
            for term in terms(chunk.text):
                counts[term] = counts.get(term, 0) + 1
            self.connection.executemany(
                "INSERT OR REPLACE INTO postings (term, chunk_id, tf) VALUES (?, ?, ?)",
                [(term, chunk.chunk_id, tf) for term, tf in counts.items()])
            self.connection.execute(
                "INSERT OR REPLACE INTO chunk_stats (chunk_id, length) VALUES (?, ?)",
                (chunk.chunk_id, len(tokenize(chunk.text, keep_stopwords=True))))

        self._refresh_meta()
        self.connection.commit()
        self.invalidate()
        return {"documents": 1, "sections": len(document.sections), "chunks": len(chunks)}

    def add_documents(self, documents: Iterable[ScientificDocument],
                      config_: ChunkingConfig | None = None) -> dict[str, int]:
        totals = {"documents": 0, "sections": 0, "chunks": 0}
        for document in documents:
            counts = self.add_document(document, config_)
            for key, value in counts.items():
                totals[key] += value
        return totals

    def remove_document(self, doc_id: str) -> int:
        chunk_ids = [row["chunk_id"] for row in self.connection.execute(
            "SELECT chunk_id FROM chunks WHERE doc_id = ?", (doc_id,))]
        self.connection.executemany("DELETE FROM postings WHERE chunk_id = ?",
                                    [(chunk_id,) for chunk_id in chunk_ids])
        self.connection.executemany("DELETE FROM chunk_stats WHERE chunk_id = ?",
                                    [(chunk_id,) for chunk_id in chunk_ids])
        self.connection.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.connection.execute("DELETE FROM sections WHERE doc_id = ?", (doc_id,))
        self.connection.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        self.connection.commit()
        self._refresh_meta()
        self.invalidate()
        return len(chunk_ids)

    def _refresh_meta(self) -> None:
        rows = self.connection.execute("SELECT chunk_id, length FROM chunk_stats").fetchall()
        total = sum(row["length"] for row in rows)
        average = total / len(rows) if rows else 0.0
        self.connection.executemany(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            [("n_chunks", str(len(rows))), ("avgdl", f"{average:.4f}"),
             ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))])

    # ------------------------------------------------------------------ reading
    def has_document(self, doc_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,)).fetchone() is not None

    def document(self, doc_id: str) -> ScientificDocument | None:
        row = self.connection.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if not row:
            return None
        sections = [
            Section(heading=section["heading"], level=section["level"],
                    label=section["label"], text=section["text"])
            for section in self.connection.execute(
                "SELECT * FROM sections WHERE doc_id = ? ORDER BY ordinal", (doc_id,))
        ]
        return ScientificDocument(
            doc_id=row["doc_id"],
            metadata=DocumentMetadata.model_validate_json(row["metadata_json"]),
            sections=sections, raw_text=row["raw_text"], sha256=row["sha256"])

    def documents(self) -> list[ScientificDocument]:
        ids = [row["doc_id"] for row in self.connection.execute(
            "SELECT doc_id FROM documents ORDER BY doc_id")]
        return [document for doc_id in ids if (document := self.document(doc_id))]

    def metadata(self) -> dict[str, DocumentMetadata]:
        return {row["doc_id"]: DocumentMetadata.model_validate_json(row["metadata_json"])
                for row in self.connection.execute("SELECT doc_id, metadata_json FROM documents")}

    def chunk(self, chunk_id: str) -> Chunk | None:
        with self._lock:
            cached = self._chunk_cache.get(chunk_id)
            if cached is not None:
                return cached
        row = self.connection.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if not row:
            return None
        chunk = _row_to_chunk(row)
        with self._lock:
            self._chunk_cache[chunk_id] = chunk
        return chunk

    def chunks(self, doc_id: str | None = None) -> list[Chunk]:
        if doc_id:
            rows = self.connection.execute(
                "SELECT * FROM chunks WHERE doc_id = ? ORDER BY section_label, ordinal",
                (doc_id,)).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM chunks ORDER BY doc_id, section_label, ordinal").fetchall()
        return [_row_to_chunk(row) for row in rows]

    def chunk_ids(self) -> list[str]:
        return [row["chunk_id"] for row in self.connection.execute("SELECT chunk_id FROM chunks")]

    # ------------------------------------------------------------------ signals
    @property
    def postings(self) -> dict[str, dict[str, int]]:
        with self._lock:
            if self._postings is None:
                postings: dict[str, dict[str, int]] = {}
                for row in self.connection.execute(
                        "SELECT term, chunk_id, tf FROM postings"):
                    postings.setdefault(row["term"], {})[row["chunk_id"]] = row["tf"]
                self._postings = postings
            return self._postings

    @property
    def lengths(self) -> dict[str, int]:
        with self._lock:
            if self._lengths is None:
                self._lengths = {
                    row["chunk_id"]: row["length"] for row in self.connection.execute(
                        "SELECT chunk_id, length FROM chunk_stats")}
            return self._lengths

    @property
    def vectors(self) -> dict[str, list[float]]:
        with self._lock:
            if self._vectors is None:
                self._vectors = {row["chunk_id"]: _unpack(row["vector"])
                                 for row in self.connection.execute(
                                     "SELECT chunk_id, vector FROM chunks")
                                 if row["vector"] is not None}
            return self._vectors

    @property
    def average_length(self) -> float:
        lengths = self.lengths
        return sum(lengths.values()) / len(lengths) if lengths else 0.0

    def vocabulary(self) -> set[str]:
        return set(self.postings)

    def stats(self) -> dict[str, object]:
        documents = self.connection.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
        sections = self.connection.execute("SELECT COUNT(*) AS n FROM sections").fetchone()
        chunks = self.connection.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        terms_count = self.connection.execute(
            "SELECT COUNT(DISTINCT term) AS n FROM postings").fetchone()
        built = self.connection.execute(
            "SELECT value FROM meta WHERE key = 'built_at'").fetchone()
        return {
            "db_path": str(self.db_path),
            "documents": documents["n"] if documents else 0,
            "sections": sections["n"] if sections else 0,
            "chunks": chunks["n"] if chunks else 0,
            "vocabulary": terms_count["n"] if terms_count else 0,
            "avg_chunk_tokens": round(self.average_length, 1),
            "embedding_dim": self.embedding_dim,
            "index_version": INDEX_VERSION,
            "built_at": built["value"] if built else None,
            "size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
        }


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"], doc_id=row["doc_id"],
        section_heading=row["section_heading"], section_label=row["section_label"],
        ordinal=row["ordinal"], text=row["text"], token_count=row["token_count"],
        starts_mid_sentence=bool(row["starts_mid_sentence"]),
    )


def open_index(path: str | Path | None = None, **kwargs: object) -> CorpusIndex:
    """Convenience constructor used by the CLI and the API."""
    return CorpusIndex(path, **kwargs)               # type: ignore[arg-type]


def index_from_documents(documents: Iterable[ScientificDocument],
                         path: str | Path | None = None) -> CorpusIndex:
    index = CorpusIndex(path)
    index.add_documents(documents)
    return index


__all__ = ["CorpusIndex", "DEFAULT_DB_PATH", "cosine", "hashing_embedding",
           "index_from_documents", "open_index"]


def _json_default(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


_ = json, _json_default          # keep the helpers importable for callers/tests
