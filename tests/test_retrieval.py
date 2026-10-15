"""
Retrieval tests.

The pure-Python helpers (cleaning, chunking, .txt extraction) always run.
The full embed+FAISS build/search path is skipped automatically if faiss /
sentence-transformers (or the embedding model) are not available offline.
"""

import pytest

import retrieval


# --------------------------- pure-python helpers ---------------------------
def test_clean_text_normalises_whitespace():
    dirty = "Hello   world\n\n\n\nThis  is\ttext"
    clean = retrieval.clean_text(dirty)
    assert "   " not in clean
    assert "\n\n\n" not in clean


def test_chunk_text_overlap_and_coverage():
    text = "word " * 500  # 2500 chars
    chunks = retrieval.chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 220 for c in chunks)  # allow small boundary slack


def test_chunk_text_empty():
    assert retrieval.chunk_text("") == []


def test_extract_text_txt(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("plain content here", encoding="utf-8")
    assert "plain content" in retrieval.extract_text(f)


# --------------------------- full pipeline (skips if deps missing) ----------
def test_build_and_search(tmp_path):
    pytest.importorskip("faiss")
    st = pytest.importorskip("sentence_transformers")
    try:
        st.SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    except Exception as exc:  # model not cached / offline
        pytest.skip(f"embedding model unavailable offline: {exc}")

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "france.txt").write_text(
        "France is a country in Europe. Its capital city is Paris.", encoding="utf-8")
    (docs / "japan.txt").write_text(
        "Japan is an island nation in Asia. Its capital is Tokyo.", encoding="utf-8")

    index_dir = tmp_path / "idx"
    r = retrieval.Retriever(index_dir=str(index_dir),
                            embed_model="sentence-transformers/all-MiniLM-L6-v2")
    stats = r.build(str(docs))
    assert stats["documents"] == 2
    r.save()

    loaded = retrieval.Retriever.load(str(index_dir))
    hits = loaded.search("What is the capital of France?", top_k=1)
    assert hits
    assert "Paris" in hits[0]["text"]
    assert hits[0]["source"] == "france.txt"
