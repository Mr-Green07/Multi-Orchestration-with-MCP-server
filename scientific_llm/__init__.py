"""scientific_llm
===============
An offline, citation-grounded literature assistant layered on the same
MCP/agent tooling as the rest of this repository.

The pipeline has five stages, each a module you can use on its own:

=================  =========================================================
``ingest``         PDF / markdown / text / arXiv / Crossref -> documents
``chunking``       section-aware chunking with overlap
``index``          persistent SQLite corpus + BM25 postings + dense vectors
``retrieval``      hybrid retrieval, query expansion, reranking, retrieval agent
``agents``         coordinator + specialists (evidence, methodology, gaps,
                   synthesis, citation validation)
=================  =========================================================

Then, for measurement: ``baselines`` (conventional RAG, single agent),
``metrics`` and ``judge`` (retrieval and answer metrics, independent support
checking), ``evaluation`` (benchmark runner, paired bootstrap), ``report``
(markdown report) and ``tracing`` (structured handoffs).

Quick start::

    from scientific_llm import CorpusIndex, ingest_directory, ScientificAgentSystem

    index = CorpusIndex("database/scientific_corpus.db")
    index.add_documents(ingest_directory("data/scientific_corpus"))
    answer = ScientificAgentSystem(index).ask("How does hybrid retrieval compare to BM25?")
    print(answer.as_text())

Command line::

    python -m scientific_llm demo
    python -m scientific_llm ingest data/scientific_corpus
    python -m scientific_llm ask "which agents validate citations?"
"""
from __future__ import annotations

__version__ = "1.0.0"

from scientific_llm.agents import (
    CitationValidatorAgent,
    CoordinatorAgent,
    EvidenceAgent,
    EvidenceSynthesisAgent,
    MethodologyComparisonAgent,
    ResearchGapAgent,
    ScientificAgentSystem,
)
from scientific_llm.baselines import ConventionalRAGSystem, SingleAgentSystem
from scientific_llm.chunking import ChunkingConfig, chunk_document, classify_section
from scientific_llm.evaluation import (
    BenchmarkDataset,
    EvaluationRunner,
    compare_systems,
    resolve_dataset,
)
from scientific_llm.index import CorpusIndex, hashing_embedding
from scientific_llm.ingest import (
    ingest_api_payload,
    ingest_arxiv_payload,
    ingest_crossref_payload,
    ingest_directory,
    ingest_markdown,
    ingest_path,
    ingest_pdf,
    ingest_text,
)
from scientific_llm.judge import Judge
from scientific_llm.models import (
    AnswerBundle,
    Chunk,
    DocumentMetadata,
    Evidence,
    ScientificDocument,
    Section,
)
from scientific_llm.retrieval import (
    HybridRetriever,
    QueryExpander,
    RetrievalAgent,
    RetrievalResult,
)
from scientific_llm.tracing import Handoff, Trace, TraceEvent

__all__ = [
    "__version__",
    # data
    "DocumentMetadata", "Section", "ScientificDocument", "Chunk", "Evidence",
    "AnswerBundle",
    # ingestion and indexing
    "ChunkingConfig", "chunk_document", "classify_section", "CorpusIndex",
    "hashing_embedding", "ingest_api_payload", "ingest_arxiv_payload",
    "ingest_crossref_payload", "ingest_directory", "ingest_markdown",
    "ingest_path", "ingest_pdf", "ingest_text",
    # retrieval
    "HybridRetriever", "QueryExpander", "RetrievalAgent", "RetrievalResult",
    # agents
    "CoordinatorAgent", "EvidenceAgent", "MethodologyComparisonAgent",
    "ResearchGapAgent", "EvidenceSynthesisAgent", "CitationValidatorAgent",
    "ScientificAgentSystem",
    # evaluation
    "BenchmarkDataset", "EvaluationRunner", "compare_systems", "resolve_dataset",
    "Judge", "ConventionalRAGSystem", "SingleAgentSystem",
    # tracing
    "Trace", "TraceEvent", "Handoff",
]
