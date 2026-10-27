"""Phase 3: specialist agents, citation validation, tracing and handoffs."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scientific_llm.agents import (
    CitationValidatorAgent,
    CoordinatorAgent,
    CoordinatorSettings,
    EvidenceAgent,
    EvidenceSynthesisAgent,
    MethodologyComparisonAgent,
    ResearchGapAgent,
    ScientificAgentSystem,
    best_sentence,
    classify_support,
    find_chunk_for_sentence,
)
from scientific_llm.index import CorpusIndex
from scientific_llm.ingest import ingest_directory
from scientific_llm.models import Evidence
from scientific_llm.retrieval import HybridRetriever, RetrievalAgent
from scientific_llm.text import sentences
from scientific_llm.tracing import Trace

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "scientific_corpus"


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    corpus = CorpusIndex(tmp_path_factory.mktemp("agents") / "corpus.db")
    corpus.add_documents(ingest_directory(CORPUS))
    yield corpus
    corpus.close()


@pytest.fixture(scope="module")
def coordinator(index):
    return CoordinatorAgent(index)


@pytest.fixture(scope="module")
def bundle(coordinator):
    return coordinator.answer("How does citation validation reduce unsupported claims?")


# ------------------------------------------------------------------ helpers
def test_best_sentence_prefers_the_matching_sentence():
    text = ("We study batteries. Citation validation removes unsupported citations "
            "by re-reading the source chunk. We conclude nothing else.")
    assert best_sentence(text, "citation validation unsupported").startswith(
        "Citation validation")


def test_support_classification_levels():
    chunk = "The validator removes 71 percent of unsupported citations."
    assert classify_support("The validator removes 71 percent of unsupported citations.",
                            chunk) == "direct"
    assert classify_support("validator removes unsupported citations percent",
                            chunk) == "paraphrase"
    assert classify_support("battery drain doubles with brightness", chunk) == "weak"


def test_find_chunk_for_sentence_locates_the_source(index):
    document = index.documents()[0]
    sentence = document.sections[-1].text.split(".")[0] + "."
    chunk_id = find_chunk_for_sentence(index, document.doc_id, sentence)
    assert chunk_id is not None
    chunk = index.chunk(chunk_id)
    assert chunk is not None and chunk.doc_id == document.doc_id


def test_find_chunk_returns_none_for_unrelated_text(index):
    document = index.documents()[0]
    assert find_chunk_for_sentence(index, document.doc_id,
                                   "quantum entanglement in cephalopods") is None


# ------------------------------------------------------------------ evidence agent
def test_evidence_agent_builds_provenance(index):
    agent = RetrievalAgent(HybridRetriever(index))
    result = agent.retrieve("what is reciprocal rank fusion?", k=5)
    evidence = EvidenceAgent().build("what is reciprocal rank fusion?", result)
    assert evidence
    for item in evidence:
        assert item.doc_id and item.chunk_id and item.quote
        assert index.chunk(item.chunk_id) is not None
        assert item.support in {"direct", "paraphrase", "weak"}
        assert item.verified is False                  # nothing verified until checked


def test_evidence_ids_are_sequential_and_unique(index):
    result = RetrievalAgent(HybridRetriever(index)).retrieve("chunking sections", k=6)
    evidence = EvidenceAgent().build("chunking sections", result)
    assert [item.evidence_id for item in evidence] == [
        f"E{number}" for number in range(1, len(evidence) + 1)]


# ------------------------------------------------------------------ methodology
def test_methodology_comparison_extracts_four_fields(index, bundle):
    documents = {document.doc_id: document for document in index.documents()}
    hits = RetrievalAgent(HybridRetriever(index)).retrieve(
        "compare methods datasets and metrics", k=6).hits
    rows = MethodologyComparisonAgent().compare(hits, documents)
    assert rows
    row = rows[0]
    assert set(row) >= {"doc_id", "title", "year", "method", "dataset", "metrics",
                        "reported"}
    assert any(row[field] for field in ("method", "dataset", "metrics"))


def test_comparison_is_emitted_only_when_asked(coordinator):
    plain = coordinator.answer("What is reciprocal rank fusion?")
    assert plain.comparison == []
    compared = coordinator.answer("Compare the retrieval methods across papers.")
    assert compared.comparison


# ------------------------------------------------------------------ gaps
def test_gap_agent_prefers_limitation_sections(index):
    hits = RetrievalAgent(HybridRetriever(index)).retrieve(
        "what are the open problems?", k=6).hits
    documents = {document.doc_id: document for document in index.documents()}
    gaps = ResearchGapAgent().find("what are the open problems?", hits, documents)
    assert gaps
    assert all(isinstance(row.get("text"), str) for row in gaps)
    assert any(row.get("doc_id") for row in gaps)


def test_gap_agent_reports_uncovered_question_terms(index):
    hits = RetrievalAgent(HybridRetriever(index)).retrieve("reciprocal rank fusion", k=3).hits
    documents = {hit.doc_id: index.document(hit.doc_id) for hit in hits}
    gaps = ResearchGapAgent().find("zebrafish optogenetics calibration", hits,
                                  {k: v for k, v in documents.items() if v})
    assert any("No retrieved passage discusses" in str(row.get("text")) for row in gaps)


# ------------------------------------------------------------------ synthesis
def test_synthesis_is_extractive_and_cited(bundle):
    assert "[E1]" in bundle.answer
    for item in bundle.evidence:
        assert f"[{item.evidence_id}]" in bundle.answer
    assert "verified quotation" in bundle.answer


def test_synthesis_refuses_to_answer_without_evidence():
    answer = EvidenceSynthesisAgent().synthesize("anything", [])
    assert "does not contain enough evidence" in answer
    assert "[E" not in answer


# ------------------------------------------------------------------ validator
def test_validator_accepts_verbatim_evidence(index):
    chunk = index.chunks()[0]
    quote = sentences(chunk.text)[0]                 # one clean sentence
    evidence = [Evidence(evidence_id="E1", claim=quote, quote=quote,
                         doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, title="t")]
    verified, ids, unsupported = CitationValidatorAgent().validate(
        f"- {quote} [E1]", evidence, index)
    assert ids == ["E1"] and verified[0].verified and unsupported == []


def test_validator_rejects_a_fabricated_quote(index):
    chunk = index.chunks()[0]
    evidence = [Evidence(evidence_id="E1", claim="x",
                         quote="Quantum tunnelling explains chocolate melting.",
                         doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, title="t")]
    verified, ids, unsupported = CitationValidatorAgent().validate(
        "- Quantum tunnelling explains chocolate melting. [E1]", evidence, index)
    assert ids == [] and verified == []
    assert unsupported, "an unverifiable quotation must be reported"


def test_validator_rejects_a_missing_chunk(index):
    evidence = [Evidence(evidence_id="E1", claim="x", quote="anything at all here",
                         doc_id="d", chunk_id="does-not-exist", title="t")]
    verified, ids, _ = CitationValidatorAgent().validate("- anything [E1]", evidence, index)
    assert ids == [] and verified == []
    assert evidence[0].verification_note == "chunk not found in the index"


def test_validator_flags_uncited_claims(index, bundle):
    _, _, unsupported = CitationValidatorAgent().validate(
        "Hybrid retrieval doubles revenue in every benchmark we ran.", [], index)
    assert unsupported


def test_every_answer_citation_is_verified(bundle):
    assert bundle.evidence, "the multi-agent answer must carry evidence"
    assert all(item.verified for item in bundle.evidence)
    assert bundle.unsupported_sentences == []


def test_answer_bundle_citations_are_the_verified_ones(bundle):
    assert bundle.citations() == [item.evidence_id for item in bundle.evidence]
    assert len(bundle.citations()) == len(set(bundle.citations()))


# ------------------------------------------------------------------ tracing
def test_trace_records_agents_in_order(bundle):
    trace = bundle.trace
    assert trace is not None
    agents = trace["agents"]
    for expected in ("coordinator", "retrieval", "evidence", "gaps", "synthesis",
                     "validator"):
        assert expected in agents
    assert trace["total_ms"] >= 0
    assert trace["trace_id"]


def test_handoffs_are_structured(bundle):
    handoffs = bundle.trace["handoffs"]
    assert {handoff["from"] for handoff in handoffs} >= {"retrieval", "evidence",
                                                        "synthesis"}
    for handoff in handoffs:
        assert handoff["to"] and handoff["reason"] and isinstance(handoff["payload"], dict)


def test_trace_span_times_and_survives_exceptions(tmp_path):
    trace = Trace("q")
    with trace.span("agent", "ok") as span:
        span.note("did work", items=3)
    with trace.span("agent", "boom"):
        pass
    try:
        with trace.span("agent", "fails"):
            raise ValueError("bad")
    except ValueError:
        pass
    actions = [event.action for event in trace.events]
    assert actions == ["ok", "boom", "fails"]
    assert trace.events[0].payload["items"] == 3
    assert "failed: ValueError" in trace.events[2].detail

    path = trace.write_jsonl(tmp_path / "traces.jsonl")
    assert path.exists() and path.read_text(encoding="utf-8").count("\n") == 1


def test_trace_summary_lines_are_readable(bundle):
    trace = Trace("q", system="multi_agent")
    trace.add("a", "step", latency_ms=1.5, detail="x")
    trace.handoff("a", "b", "reason")
    lines = trace.summary_lines()
    assert "trace" in lines[0]
    assert any("handoff a -> b" in line for line in lines)


# ------------------------------------------------------------------ coordinator
def test_coordinator_returns_a_complete_bundle(coordinator):
    bundle = coordinator.answer("What fusion method do the authors use?")
    assert bundle.system == "multi_agent"
    assert bundle.answer and bundle.evidence
    assert bundle.retrieved_doc_ids
    assert bundle.latency_ms > 0
    assert bundle.trace is not None


def test_coordinator_trace_can_be_disabled(index):
    coordinator = CoordinatorAgent(index, settings=CoordinatorSettings(keep_trace=False))
    bundle = coordinator.answer("what is bm25?")
    assert bundle.trace is None
    assert bundle.answer, "answers must still be produced without a trace"


def test_answer_bundle_renders_text_with_references(bundle):
    rendered = bundle.as_text()
    assert "Evidence" in rendered
    assert "[E1]" in rendered


def test_system_facade_is_reusable(index):
    system = ScientificAgentSystem(index)
    first = system.ask("what is reciprocal rank fusion?")
    second = system.ask("what is reciprocal rank fusion?")
    assert first.answer == second.answer


def test_wants_comparison_detects_cues():
    assert CoordinatorAgent.wants_comparison("Compare the two approaches")
    assert CoordinatorAgent.wants_comparison("A versus B")
    assert not CoordinatorAgent.wants_comparison("What is BM25?")


def test_empty_index_answers_honestly(tmp_path):
    empty = CorpusIndex(tmp_path / "empty.db")
    bundle = CoordinatorAgent(empty).answer("anything at all")
    assert bundle.evidence == []
    assert "does not contain enough evidence" in bundle.answer
    empty.close()


def test_answer_is_deterministic(coordinator):
    first = coordinator.answer("How does section-aware chunking help?")
    second = coordinator.answer("How does section-aware chunking help?")
    assert first.answer == second.answer
    assert [item.chunk_id for item in first.evidence] == [
        item.chunk_id for item in second.evidence]
