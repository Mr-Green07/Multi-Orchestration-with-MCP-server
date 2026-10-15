"""
retrieval.py
============
Fully-local document retrieval (RAG).

Pipeline:
    PDF / TXT / MD / DOCX
        -> text extraction (PyMuPDF for PDF, python-docx for DOCX)
        -> cleaning (whitespace normalisation)
        -> chunking (character windows with overlap)
        -> local embeddings (sentence-transformers)
        -> FAISS index (cosine similarity via normalised inner product)
        -> save to disk  /  load from disk (offline)
        -> top-k similarity search

All heavy imports (numpy, faiss, sentence_transformers, fitz, docx) are done
lazily inside methods so the rest of the project imports cleanly without them.

Index files written to ``<index_dir>/``:
    index.faiss   -- the FAISS vector index
    meta.json     -- chunk metadata: [{id, source, chunk_index, text}, ...]
    config.json   -- {embed_model, dim, chunk_size, overlap, normalize}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

import security

# Default local embedding model. Point --embed-model at a local directory for
# guaranteed-offline use (see README). A bare name works only if it is already
# cached locally by sentence-transformers.
DEFAULT_EMBED_MODEL = str(security.MODELS_DIR / "all-MiniLM-L6-v2")

_SUPPORTED_EXT = {".pdf", ".txt", ".md", ".markdown", ".docx"}


# ---------------------------------------------------------------------------
# Text extraction + cleaning + chunking
# ---------------------------------------------------------------------------
def extract_text(path: Path) -> str:
    """Extract raw text from a supported document."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF
        parts = []
        with fitz.open(path) as doc:
            for page in doc:
                parts.append(page.get_text("text"))
        return "\n".join(parts)
    if suffix == ".docx":
        import docx  # python-docx
        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs)
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported document type: {suffix}")


def clean_text(text: str) -> str:
    """Normalise whitespace and strip control characters."""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> List[str]:
    """Split *text* into overlapping character windows on word boundaries."""
    text = text.strip()
    if not text:
        return []
    if overlap >= chunk_size:
        overlap = chunk_size // 4

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        # Prefer to break on whitespace near the window end.
        if end < n:
            window = text[start:end]
            cut = window.rfind(" ")
            if cut > chunk_size * 0.5:
                end = start + cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------
class Retriever:
    """Builds, saves, loads and queries a local FAISS document index."""

    def __init__(self, index_dir: str, embed_model: str = DEFAULT_EMBED_MODEL):
        self.index_dir = Path(index_dir)
        self.embed_model_name = embed_model
        self._model = None          # lazy SentenceTransformer
        self._index = None          # lazy faiss index
        self.meta: List[dict] = []  # chunk metadata
        self.config: dict = {}

    # -- embedding model (lazy, offline) --
    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.embed_model_name)
        return self._model

    def _embed(self, texts: List[str]):
        import numpy as np
        model = self._get_model()
        vectors = model.encode(
            texts, convert_to_numpy=True, normalize_embeddings=True,
            show_progress_bar=False, batch_size=32,
        )
        return np.asarray(vectors, dtype="float32")

    # -- build --
    def build(self, documents_dir: str, chunk_size: int = 800, overlap: int = 120) -> dict:
        import faiss

        docs_dir = Path(documents_dir)
        files = [p for p in sorted(docs_dir.rglob("*"))
                 if p.is_file() and p.suffix.lower() in _SUPPORTED_EXT]
        if not files:
            raise FileNotFoundError(
                f"No supported documents ({', '.join(sorted(_SUPPORTED_EXT))}) found in {docs_dir}."
            )

        self.meta = []
        all_chunks: List[str] = []
        skipped = []
        for path in files:
            try:
                raw = extract_text(path)
            except Exception as exc:
                skipped.append((path.name, str(exc)))
                continue
            cleaned = clean_text(raw)
            source = str(path.relative_to(docs_dir))
            for idx, chunk in enumerate(chunk_text(cleaned, chunk_size, overlap)):
                self.meta.append({
                    "id": len(all_chunks),
                    "source": source,
                    "chunk_index": idx,
                    "text": chunk,
                })
                all_chunks.append(chunk)

        if not all_chunks:
            raise ValueError("No text could be extracted from the documents.")

        vectors = self._embed(all_chunks)
        dim = int(vectors.shape[1])
        index = faiss.IndexFlatIP(dim)  # inner product on normalised vectors == cosine
        index.add(vectors)
        self._index = index
        self.config = {
            "embed_model": self.embed_model_name,
            "dim": dim,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "normalize": True,
            "num_documents": len(files),
            "num_chunks": len(all_chunks),
        }
        return {"documents": len(files), "chunks": len(all_chunks), "skipped": skipped}

    # -- persistence --
    def save(self) -> None:
        import faiss
        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_dir / "index.faiss"))
        (self.index_dir / "meta.json").write_text(
            json.dumps(self.meta, ensure_ascii=False), encoding="utf-8")
        (self.index_dir / "config.json").write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, index_dir: str, embed_model: Optional[str] = None) -> "Retriever":
        import faiss
        index_path = Path(index_dir)
        faiss_file = index_path / "index.faiss"
        meta_file = index_path / "meta.json"
        config_file = index_path / "config.json"
        if not (faiss_file.exists() and meta_file.exists()):
            raise FileNotFoundError(f"No index found in '{index_dir}'. Run build_index.py first.")

        config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        model_name = embed_model or config.get("embed_model", DEFAULT_EMBED_MODEL)
        obj = cls(index_dir=str(index_path), embed_model=model_name)
        obj._index = faiss.read_index(str(faiss_file))
        obj.meta = json.loads(meta_file.read_text(encoding="utf-8"))
        obj.config = config
        return obj

    # -- search --
    def search(self, query: str, top_k: int = 4) -> List[dict]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")
        if self._index is None:
            raise RuntimeError("Index is not loaded.")
        top_k = max(1, min(int(top_k), len(self.meta)))
        qvec = self._embed([query])
        scores, indices = self._index.search(qvec, top_k)
        hits = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.meta):
                continue
            item = dict(self.meta[idx])
            item["score"] = float(score)
            hits.append(item)
        return hits


def load_if_exists(index_dir: str, embed_model: Optional[str] = None) -> Optional[Retriever]:
    """Return a loaded Retriever, or ``None`` if no index exists / load fails."""
    try:
        return Retriever.load(index_dir, embed_model)
    except FileNotFoundError:
        return None
