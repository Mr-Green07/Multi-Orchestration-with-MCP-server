"""Phase 1: schema, ingestion, chunking, persistent index, evidence contract."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scientific_llm.chunking import ChunkingConfig, chunk_document, classify_section
from scientific_llm.index import CorpusIndex, cosine, hashing_embedding
from scientific_llm.ingest import (
    IngestionError,
    ingest_arxiv_payload,
    ingest_crossref_payload,
    ingest_markdown,
    ingest_path,
    ingest_text,
    make_doc_id,
    parse_front_matter,
)
from scientific_llm.models import DocumentMetadata, Evidence, ScientificDocument
from scientific_llm.text import stem, terms, tokenize

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "scientific_corpus"

SAMPLE = """---
title: Retrieval Baselines Revisited
authors: A. One; B. Two
year: 2021
venue: Test Journal
doi: 10.1000/t.2021.1
keywords: retrieval, bm25
---

# Abstract

We revisit sparse retrieval baselines and find they remain competitive. This
sentence exists to give the abstract enough words to be a real chunk candidate.

# 1 Introduction

Sparse retrieval is cheap. Dense retrieval is expensive. The trade-off matters for
scientific search where vocabulary is specialised and identifiers are common.

# 2 Methods

We use BM25 with k1 of 1.5 and b of 0.75 over section-aware chunks of 220 tokens.
We evaluate on a benchmark of 2000 questions with gold passage annotations.

# 3 Results

BM25 reaches recall at ten of 0.61 while the dense retriever reaches 0.66 and the
hybrid reaches 0.78 on the same questions.

# 4 Limitations

We do not evaluate long documents, and the corpus is restricted to open access
papers, which biases the venue distribution towards well-funded groups.

# 5 Conclusion

Sparse baselines remain a required comparison for any new retriever.
"""


# ------------------------------------------------------------------ metadata schema
def test_metadata_requires_a_title_and_validates_year():
    assert DocumentMetadata(title="  A paper  ").title == "A paper"
    with pytest.raises(ValueError):
        DocumentMetadata(title="   ")
    with pytest.raises(ValueError):
        DocumentMetadata(title="Paper", year=1234)


def test_metadata_defaults_are_empty_not_invented():
    metadata = DocumentMetadata(title="Paper")
    assert metadata.authors == [] and metadata.doi is None and metadata.year is None
    assert metadata.source == "manual"


# ------------------------------------------------------------------ text utilities
def test_tokenizer_keeps_domain_tokens_and_drops_stopwords():
    tokens = tokenize("The bi-encoder and BM25 both retrieve")
    assert "bi-encoder" in tokens and "bm25" in tokens
    assert "the" not in tokens and "and" not in tokens


@pytest.mark.parametrize("words,shared", [
    (("retrieval", "retrievals"), True),
    (("limitation", "limitations"), True),
    (("evaluation", "evaluating", "evaluated"), True),
    (("dataset", "data"), False),
    (("benchmark", "benchmarks"), True),
])
def test_stemmer_groups_inflections(words, shared):
    stems = {stem(word) for word in words}
    assert (len(stems) == 1) is shared


def test_stemmer_leaves_short_words_alone():
    assert stem("bm25") == "bm25"
    assert stem("top") == "top"


# ------------------------------------------------------------------ ingestion
def test_front_matter_parsing_handles_fences_and_bare_headers():
    metadata, body = parse_front_matter(SAMPLE)
    assert metadata["title"] == "Retrieval Baselines Revisited"
    assert metadata["year"] == "2021"
    assert body.lstrip().startswith("# Abstract")

    bare_meta, bare_body = parse_front_matter("Title: X\nAuthors: Y\n\nBody text")
    assert bare_meta == {"title": "X", "authors": "Y"}
    assert bare_body.strip() == "Body text"


def test_ingest_markdown_builds_metadata_and_sections():
    document = ingest_markdown(SAMPLE)
    assert document.metadata.title == "Retrieval Baselines Revisited"
    assert document.metadata.authors == ["A. One", "B. Two"]
    assert document.metadata.year == 2021
    assert document.metadata.doi == "10.1000/t.2021.1"
    labels = [section.label for section in document.sections]
    assert labels[0] == "abstract"
    assert "methods" in labels and "limitations" in labels and "results" in labels
    assert document.abstract().startswith("We revisit sparse retrieval")


def test_document_ids_are_content_addressed_and_stable():
    first = ingest_markdown(SAMPLE)
    second = ingest_markdown(SAMPLE)
    assert first.doc_id == second.doc_id
    assert first.doc_id.startswith("retrieval-baselines-revisited-")
    assert first.sha256 == second.sha256


def test_ingest_rejects_documents_without_a_title():
    with pytest.raises(IngestionError):
        ingest_markdown("no front matter and no heading, just text")


def test_ingest_text_splits_on_caps_headings():
    raw = "ABSTRACT\nWe study things carefully.\n\n1 INTRODUCTION\nRetrieval is old.\n\n" \
          "2 METHODS\nWe use BM25.\n"
    document = ingest_text(raw, title="Plain Paper")
    labels = [section.label for section in document.sections]
    assert labels == ["abstract", "introduction", "methods"]


def test_arxiv_payload_ingestion():
    payload = {"entries": [{
        "title": "Scaling Sparse Retrieval",
        "summary": "We scale sparse retrieval to a billion passages with sharding.",
        "published": "2023-05-01T00:00:00Z",
        "id": "http://arxiv.org/abs/2305.00001v1",
        "authors": [{"name": "A. Researcher"}, {"name": "B. Author"}],
        "categories": ["cs.IR"],
        "comment": "doi: 10.1000/arxiv.2305.00001",
    }]}
    documents = ingest_arxiv_payload(payload)
    assert len(documents) == 1
    metadata = documents[0].metadata
    assert metadata.authors == ["A. Researcher", "B. Author"]
    assert metadata.year == 2023 and metadata.venue == "arXiv"
    assert metadata.doi == "10.1000/arxiv.2305.00001"
    assert documents[0].sections[0].label == "abstract"


def test_arxiv_atom_xml_is_supported():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Atom Paper</title>
        <summary>Retrieval from an Atom feed.</summary>
        <published>2022-01-02T00:00:00Z</published>
        <id>http://arxiv.org/abs/2201.00002</id>
        <author><name>C. Writer</name></author>
        <category term="cs.CL"/>
      </entry>
    </feed>"""
    documents = ingest_arxiv_payload(xml)
    assert documents[0].metadata.title == "Atom Paper"
    assert documents[0].metadata.authors == ["C. Writer"]


def test_crossref_payload_ingestion():
    payload = {"message": {"items": [{
        "title": ["A Crossref Paper"],
        "author": [{"given": "D.", "family": "Scholar"}],
        "issued": {"date-parts": [[2020, 3]]},
        "container-title": ["Journal of Tests"],
        "DOI": "10.1000/cr.2020.1",
        "URL": "https://example.org/cr",
        "abstract": "<jats:p>We test <jats:italic>things</jats:italic>.</jats:p>",
        "subject": ["retrieval"],
    }]}}
    documents = ingest_crossref_payload(payload)
    metadata = documents[0].metadata
    assert metadata.title == "A Crossref Paper"
    assert metadata.authors == ["D. Scholar"]
    assert metadata.year == 2020
    assert metadata.venue == "Journal of Tests"
    assert "<jats:" not in (metadata.abstract or "")


def test_ingest_path_dispatches_and_rejects_unknown_suffix(tmp_path):
    path = tmp_path / "paper.md"
    path.write_text(SAMPLE, encoding="utf-8")
    assert ingest_path(path)[0].metadata.title == "Retrieval Baselines Revisited"

    bad = tmp_path / "paper.docx"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(IngestionError):
        ingest_path(bad)


def test_ingest_pdf_reads_a_real_pdf(tmp_path):
    from scientific_llm.ingest import ingest_pdf
    from scripts.make_sample_pdf import build_pdf

    text = ("Abstract\nWe study scientific retrieval in depth.\n"
            "Introduction\nRetrieval is the first stage.\n"
            "Methods\nWe use BM25 over section aware chunks.\n"
            "Results\nRecall at ten improves substantially.\n"
            "Limitations\nWe do not evaluate long documents.\n")
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(build_pdf(text, title="PDF Paper"))
    document = ingest_pdf(str(pdf_path), title="PDF Paper")
    assert "BM25" in document.raw_text
    labels = {section.label for section in document.sections}
    assert {"abstract", "methods", "results", "limitations"} <= labels


# ------------------------------------------------------------------ chunking
@pytest.mark.parametrize("heading,label", [
    ("Abstract", "abstract"), ("1 Introduction", "introduction"),
    ("3.1 Experimental Setup", "methods"), ("Results and Discussion", "results"),
    ("Threats to Validity", "limitations"), ("Future Directions", "future work"),
    ("Bibliography", "references"), ("Acknowledgements", "other"),
])
def test_section_classification(heading, label):
    assert classify_section(heading) == label


def test_chunks_never_cross_sections_and_record_provenance():
    document = ingest_markdown(SAMPLE)
    chunks = chunk_document(document)
    assert chunks
    for chunk in chunks:
        section = next(section for section in document.sections
                       if section.heading == chunk.section_heading)
        assert chunk.text in section.text
        assert chunk.doc_id == document.doc_id
        assert chunk.token_count > 0
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_chunking_splits_long_sections_with_overlap():
    long_body = " ".join([f"Sentence number {index} about retrieval quality." for index in
                          range(120)])
    document = ingest_markdown(f"---\ntitle: Long\n---\n\n# Methods\n\n{long_body}\n")
    config = ChunkingConfig(target_tokens=60, overlap_tokens=15)
    chunks = chunk_document(document, config)
    assert len(chunks) > 2
    assert all(chunk.token_count <= config.target_tokens + 25 for chunk in chunks)


def test_chunking_config_rejects_impossible_settings():
    with pytest.raises(ValueError):
        ChunkingConfig(target_tokens=20)
    with pytest.raises(ValueError):
        ChunkingConfig(target_tokens=100, overlap_tokens=200)


# ------------------------------------------------------------------ index
@pytest.fixture()
def index(tmp_path):
    corpus = CorpusIndex(tmp_path / "corpus.db")
    corpus.add_documents(ingest_markdown(SAMPLE) for _ in range(1))
    yield corpus
    corpus.close()


def test_index_round_trips_a_document(index):
    document = next(iter(index.documents()))
    assert document.metadata.title == "Retrieval Baselines Revisited"
    assert len(document.sections) >= 5
    assert index.has_document(document.doc_id)
    assert index.chunk(index.chunks()[0].chunk_id) is not None


def test_index_is_persistent_across_connections(tmp_path):
    path = tmp_path / "persist.db"
    with CorpusIndex(path) as first:
        first.add_documents([ingest_markdown(SAMPLE)])
        doc_id = first.documents()[0].doc_id
    with CorpusIndex(path) as second:
        assert second.has_document(doc_id)
        assert second.stats()["chunks"] > 0
        assert second.postings, "postings must be rebuilt from disk"


def test_reingesting_replaces_rather_than_duplicates(tmp_path):
    with CorpusIndex(tmp_path / "dup.db") as corpus:
        document = ingest_markdown(SAMPLE)
        first = corpus.add_documents([document])
        second = corpus.add_documents([document])
        assert first == second
        assert corpus.stats()["documents"] == 1


def test_removing_a_document_clears_its_postings(index):
    doc_id = next(iter(index.metadata()))
    removed = index.remove_document(doc_id)
    assert removed > 0
    assert not index.has_document(doc_id)
    assert index.stats()["chunks"] == 0
    assert not index.postings


def test_postings_and_stats_are_consistent(index):
    assert index.lengths and len(index.lengths) == index.stats()["chunks"]
    assert index.average_length > 0
    assert "retriev" in index.vocabulary()      # "retrieval" stems to "retriev"


def test_hashing_embedding_is_normalised_and_deterministic():
    left = hashing_embedding("retrieval augmented generation", dim=64)
    right = hashing_embedding("retrieval augmented generation", dim=64)
    assert left == right
    assert abs(sum(value * value for value in left) - 1.0) < 1e-6
    assert len(left) == 64
    assert cosine(left, right) == pytest.approx(1.0, abs=1e-6)


def test_embedding_similarity_tracks_vocabulary_overlap():
    query = hashing_embedding("dense retrieval vector embedding", dim=256)
    near = hashing_embedding("vector embedding for dense retrieval", dim=256)
    far = hashing_embedding("battery level and screen brightness", dim=256)
    assert cosine(query, near) > cosine(query, far)


def test_custom_embedder_is_used_when_supplied(tmp_path):
    calls: list[str] = []

    def embedder(text: str) -> list[float]:
        calls.append(text)
        return [1.0, 0.0, 0.0]

    with CorpusIndex(tmp_path / "custom.db", embedding_dim=3, embedder=embedder) as corpus:
        corpus.add_documents([ingest_markdown(SAMPLE)])
        assert calls, "the supplied embedder must be called at index time"
        assert corpus.stats()["embedding_dim"] == 3


# ------------------------------------------------------------------ evidence contract
def test_evidence_citation_formatting():
    evidence = Evidence(evidence_id="E1", claim="c", quote="q", doc_id="d",
                        chunk_id="c1", title="A Title", authors=["A. One"], year=2021,
                        section="results")
    assert evidence.citation() == "A. One, 2021"
    assert evidence.as_reference().startswith("[E1] A. One, 2021 - A Title")
    assert evidence.verified is False            # nothing is verified by construction


def test_make_doc_id_is_slug_plus_hash():
    doc_id = make_doc_id("A Very Long Title: With Punctuation!", "body")
    assert doc_id.startswith("a-very-long-title-with-punctuation-")
    assert len(doc_id.rsplit("-", 1)[-1]) == 8


def test_document_citation_line_handles_one_two_and_many_authors():
    def doc(authors):
        return ScientificDocument(doc_id="x", metadata=DocumentMetadata(
            title="T", authors=authors, year=2020))

    assert doc(["A"]).citations_line().startswith("A (2020)")
    assert doc(["A", "B"]).citations_line().startswith("A & B (2020)")
    assert doc(["A", "B", "C"]).citations_line().startswith("A et al. (2020)")


def test_terms_are_stemmed_and_stopword_free():
    assert terms("The evaluations of retrievers") == ["evaluat", "retriever"]
