"""Phase 2: hybrid retrieval, expansion, reranking, retrieval agent, Recall@k."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scientific_llm.chunking import ChunkingConfig
from scientific_llm.index import CorpusIndex
from scientific_llm.ingest import ingest_directory, ingest_markdown
from scientific_llm.metrics import mean, precision_at_k, recall_at_k, reciprocal_rank
from scientific_llm.retrieval import (
    SECTION_HINTS,
    HybridRetriever,
    QueryExpander,
    RetrievalAgent,
)

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "scientific_corpus"

MINI = """---
title: Fusion Study
authors: A. Author
year: 2022
venue: Test
---

# Abstract

We fuse sparse and dense retrieval with reciprocal rank fusion and report recall.

# 1 Introduction

Hybrid retrieval combines a lexical retriever with a dense bi-encoder.

# 2 Methods

BM25 is computed with k1 of 1.5. The dense side uses a bi-encoder embedding.

# 3 Results

Fusion improves recall at ten from 0.61 to 0.78 on the benchmark questions.

# 4 Limitations

We do not evaluate long documents or multilingual queries.
"""

OTHER = """---
title: Battery Telemetry Study
authors: B. Author
year: 2019
venue: Test
---

# Abstract

We measure laptop battery drain under different screen brightness settings.

# 1 Methods

We log battery percentage every ten seconds while varying brightness.

# 2 Results

Brightness above eighty percent doubles battery drain within two hours.
"""


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    path = tmp_path_factory.mktemp("sci") / "corpus.db"
    index = CorpusIndex(path)
    index.add_documents(ingest_directory(CORPUS))
    yield index
    index.close()


@pytest.fixture()
def mini(tmp_path):
    index = CorpusIndex(tmp_path / "mini.db")
    index.add_documents([ingest_markdown(MINI), ingest_markdown(OTHER)])
    yield index
    index.close()


# ------------------------------------------------------------------ metrics
def test_recall_and_precision_definitions():
    assert recall_at_k(["a", "b", "c"], ["b"], 3) == 1.0
    assert recall_at_k(["a", "b", "c"], ["b"], 1) == 0.0
    assert recall_at_k(["a"], [], 5) == 0.0
    assert precision_at_k(["a", "b"], ["a", "z"], 2) == 0.5
    assert precision_at_k([], ["a"], 5) == 0.0
    assert reciprocal_rank(["x", "y", "gold"], ["gold"]) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x"], ["gold"]) == 0.0
    assert mean([]) == 0.0 and mean([1, 3]) == 2.0


# ------------------------------------------------------------------ lexical + dense
def test_bm25_prefers_the_matching_document(mini):
    retriever = HybridRetriever(mini, use_expansion=False)
    scores = retriever.bm25_scores("battery brightness")
    ranked = sorted(scores.items(), key=lambda item: -item[1])
    top_chunk = mini.chunk(ranked[0][0])
    assert top_chunk is not None and top_chunk.doc_id.startswith("battery-telemetry")


def test_dense_scores_are_cosine_similarities(mini):
    retriever = HybridRetriever(mini)
    scores = retriever.dense_scores("reciprocal rank fusion")
    assert scores
    assert all(-1.01 <= value <= 1.01 for value in scores.values())


def test_retrieval_modes_are_selectable(mini):
    for mode in ("hybrid", "bm25", "dense"):
        result = HybridRetriever(mini, mode=mode).search("fusion recall", k=3)
        assert result.hits, mode
    with pytest.raises(ValueError):
        HybridRetriever(mini, mode="magic")


def test_fusion_combines_both_signals(mini):
    hybrid = HybridRetriever(mini).search("bi-encoder fusion", k=4)
    dense_only = HybridRetriever(mini, mode="dense").search("bi-encoder fusion", k=4)
    lexical_only = HybridRetriever(mini, mode="bm25").search("bi-encoder fusion", k=4)
    assert hybrid.hits
    assert dense_only.hits and lexical_only.hits
    # fusion order must be a genuine combination, not a copy of one list
    assert [h.chunk_id for h in hybrid.hits] != [h.chunk_id for h in dense_only.hits] or \
           [h.chunk_id for h in hybrid.hits] != [h.chunk_id for h in lexical_only.hits]


def test_every_hit_exposes_its_intermediate_scores(mini):
    result = HybridRetriever(mini).search("fusion", k=3)
    hit = result.hits[0]
    assert hit.bm25 >= 0 and hit.dense != 0 and hit.rerank > 0
    payload = hit.as_dict()
    assert {"score", "bm25", "dense", "rerank", "matched_terms"} <= set(payload)


# ------------------------------------------------------------------ expansion
def test_thesaurus_expansion_adds_synonyms(mini):
    expander = QueryExpander(mini)
    expansions = expander.expand("dense retrieval with reranking")
    joined = " ".join(expansions)
    assert "embedding" in joined or "bi-encoder" in joined
    assert "cross-encoder" in joined or "re-rank" in joined


def test_acronym_expansion_is_mined_from_the_corpus(tmp_path):
    index = CorpusIndex(tmp_path / "acr.db")
    index.add_documents([ingest_markdown(
        "---\ntitle: Acronym Paper\n---\n\n# Abstract\n"
        "We study Retrieval-Augmented Generation (RAG) on scientific text, and "
        "Large Language Model (LLM) prompting with retrieval grounding.\n")])
    expander = QueryExpander(index)
    assert expander.acronym_map().get("rag") == "Retrieval-Augmented Generation"
    expanded = " ".join(expander.expand("does RAG work?")).lower().replace("-", " ")
    assert expanded.count("retrieval augmented generation") == 1, "synonyms must be deduplicated"
    index.close()


def test_expansion_can_be_disabled(mini):
    with_expansion = HybridRetriever(mini, use_expansion=True).search("bm25", k=2)
    without = HybridRetriever(mini, use_expansion=False).search("bm25", k=2)
    assert with_expansion.expanded_terms
    assert without.expanded_terms == []


def test_pseudo_relevance_feedback_terms_come_from_top_chunks(mini):
    expander = QueryExpander(mini)
    chunks = mini.chunks()[:2]
    feedback = expander.feedback_terms(chunks, "battery")
    assert feedback
    assert all("battery" not in term for term in feedback)


# ------------------------------------------------------------------ reranking
def test_reranking_rewards_section_hints():
    assert "limitations" in {
        section for cues, sections in SECTION_HINTS.items() if "gap" in cues
        for section in sections}
    targets = HybridRetriever._section_targets("what are the limitations and open gaps?")
    assert "limitations" in targets and "future work" in targets
    assert HybridRetriever._section_targets("how much battery is left?") == set()


def test_phrase_bonus_rewards_verbatim_bigrams():
    assert HybridRetriever._phrase_bonus("reciprocal rank fusion",
                                         "they use reciprocal rank fusion") == 1.0
    assert HybridRetriever._phrase_bonus("reciprocal rank fusion",
                                         "fusion of ranks") < 1.0
    assert HybridRetriever._phrase_bonus("fusion", "fusion") == 0.0


def test_diversification_limits_chunks_per_document(corpus):
    result = HybridRetriever(corpus).search(
        "section aware chunking of method sections", k=8)
    per_doc: dict[str, int] = {}
    for hit in result.hits:
        per_doc[hit.doc_id] = per_doc.get(hit.doc_id, 0) + 1
    assert all(count <= 3 for count in per_doc.values())


# ------------------------------------------------------------------ retrieval agent
def test_retrieval_agent_records_stages(corpus):
    agent = RetrievalAgent(HybridRetriever(corpus))
    result = agent.retrieve("how does citation validation reduce unsupported claims?", k=5)
    stages = [stage["stage"] for stage in result.stages]
    assert stages[0] == "lexical"
    assert "fusion" in stages and "judge" in stages and "select" in stages
    assert result.rounds >= 1
    assert result.took_ms >= 0


def test_retrieval_agent_never_returns_duplicate_chunks(corpus):
    result = RetrievalAgent(HybridRetriever(corpus)).retrieve(
        "hybrid retrieval and reranking latency", k=8)
    ids = [hit.chunk_id for hit in result.hits]
    assert len(ids) == len(set(ids))


def test_retrieval_agent_stops_early_when_evidence_is_sufficient(corpus):
    agent = RetrievalAgent(HybridRetriever(corpus), max_rounds=2, min_docs=2,
                           score_floor=0.1)
    result = agent.retrieve("what is reciprocal rank fusion?", k=6)
    assert result.rounds == 1
    assert any(stage.get("sufficient") is True for stage in result.stages)


def test_retrieval_agent_iterates_when_the_floor_is_unreachable(corpus):
    agent = RetrievalAgent(HybridRetriever(corpus), max_rounds=2, min_docs=9,
                           score_floor=0.99)
    result = agent.retrieve("what is reciprocal rank fusion?", k=6)
    assert result.rounds == 2
    assert any(stage["stage"] == "feedback" for stage in result.stages)


def test_result_document_ids_are_distinct_and_ordered(corpus):
    result = RetrievalAgent(HybridRetriever(corpus)).retrieve("limitations of chunking", k=6)
    doc_ids = result.doc_ids()
    assert len(doc_ids) == len(set(doc_ids))
    assert all(doc_id for doc_id in doc_ids)


# ------------------------------------------------------------------ recall@k evaluation
def test_recall_at_k_on_the_bundled_corpus(corpus):
    """Every benchmark question must find at least one gold paper in the top 10."""
    from scientific_llm.evaluation import BenchmarkDataset, resolve_dataset

    dataset = resolve_dataset(BenchmarkDataset.load(), corpus)
    agent = RetrievalAgent(HybridRetriever(corpus))
    scores = []
    for question in dataset:
        result = agent.retrieve(question.question, k=10)
        scores.append(recall_at_k(result.doc_ids(), question.gold_docs, 10))
    assert mean(scores) >= 0.9, f"mean recall@10 was {mean(scores):.3f}"
    assert min(scores) > 0, "at least one gold document per question must be retrieved"


def test_retrieval_is_deterministic(corpus):
    agent = RetrievalAgent(HybridRetriever(corpus))
    first = agent.retrieve("reranking latency budget", k=5)
    second = agent.retrieve("reranking latency budget", k=5)
    assert [hit.chunk_id for hit in first.hits] == [hit.chunk_id for hit in second.hits]
    assert [round(hit.score, 6) for hit in first.hits] == \
        [round(hit.score, 6) for hit in second.hits]


def test_chunking_config_changes_the_index(tmp_path):
    document = ingest_directory(CORPUS)[0]
    small = CorpusIndex(tmp_path / "small.db")
    large = CorpusIndex(tmp_path / "large.db")
    small.add_documents([document], ChunkingConfig(target_tokens=60, overlap_tokens=10))
    large.add_documents([document], ChunkingConfig(target_tokens=400, overlap_tokens=40))
    assert small.stats()["chunks"] > large.stats()["chunks"]
    small.close()
    large.close()
