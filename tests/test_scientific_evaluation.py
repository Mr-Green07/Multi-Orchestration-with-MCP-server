"""Phase 4: benchmark dataset, baselines, metrics, runner, statistics, report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scientific_llm import metrics
from scientific_llm.agents import CoordinatorAgent
from scientific_llm.baselines import ConventionalRAGSystem, SingleAgentSystem
from scientific_llm.evaluation import (
    BenchmarkDataset,
    BenchmarkQuestion,
    EvaluationRunner,
    compare_systems,
    comparison_table,
    markdown_table,
    paired_bootstrap,
    resolve_dataset,
)
from scientific_llm.index import CorpusIndex
from scientific_llm.ingest import ingest_directory
from scientific_llm.judge import Judge
from scientific_llm.models import AnswerBundle, Evidence
from scientific_llm.report import build_report, metric_sanity_check

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "scientific_corpus"
BENCHMARK = ROOT / "data" / "benchmark" / "questions.json"


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    corpus = CorpusIndex(tmp_path_factory.mktemp("eval") / "corpus.db")
    corpus.add_documents(ingest_directory(CORPUS))
    yield corpus
    corpus.close()


@pytest.fixture(scope="module")
def dataset(index):
    return resolve_dataset(BenchmarkDataset.load(BENCHMARK), index)


@pytest.fixture(scope="module")
def results(index, dataset):
    runner = EvaluationRunner(dataset, k=5, index=index)
    runner.run_all({
        "conventional_rag": ConventionalRAGSystem(index),
        "single_agent": SingleAgentSystem(index),
        "multi_agent": CoordinatorAgent(index),
    })
    return runner


# ------------------------------------------------------------------ dataset
def test_benchmark_loads_and_validates():
    dataset = BenchmarkDataset.load(BENCHMARK)
    assert len(dataset) >= 15
    assert dataset.name == "scientific_rag_benchmark_v1"
    assert {"factual", "comparison", "methodology", "gap"} <= set(dataset.categories())
    for question in dataset:
        assert question.question_id and question.question
        assert question.gold_docs
        assert question.key_points


def test_question_requires_text():
    with pytest.raises(ValueError):
        BenchmarkQuestion.from_dict({"gold_docs": ["x"]})


def test_dataset_rejects_an_empty_question_list():
    with pytest.raises(ValueError):
        BenchmarkDataset([])


def test_resolve_dataset_maps_prefixes_to_real_ids(dataset, index):
    available = {document.doc_id for document in index.documents()}
    for question in dataset:
        assert set(question.gold_docs) <= available


def test_resolve_dataset_reports_unknown_documents(index):
    broken = BenchmarkDataset([BenchmarkQuestion(
        question_id="qX", question="?", gold_docs=["no-such-paper"])])
    with pytest.raises(ValueError, match="no-such-paper"):
        resolve_dataset(broken, index)


def test_categories_are_deduplicated(dataset):
    categories = dataset.categories()
    assert len(categories) == len(set(categories))


# ------------------------------------------------------------------ metrics
def _bundle(answer: str, evidence: list[Evidence], unsupported: list[str] | None = None
            ) -> AnswerBundle:
    return AnswerBundle(question="q", answer=answer, evidence=evidence,
                        unsupported_sentences=unsupported or [], latency_ms=10.0)


def _evidence(evidence_id: str, doc_id: str = "d1", verified: bool = True,
              support: str = "direct") -> Evidence:
    return Evidence(evidence_id=evidence_id, claim="c", quote="q", doc_id=doc_id,
                    chunk_id="c1", title="t", support=support, verified=verified)


def test_claim_splitting_treats_a_bullet_with_a_marker_as_one_claim():
    answer = ("Lead in that is not a claim.\n"
              "- Retrieval fusion improves recall at ten substantially. [E1]\n"
              "- A second claim about reranking latency. [E2]")
    claims = metrics.claim_sentences(answer)
    assert len(claims) == 2
    assert claims[0].endswith("[E1]")


def test_citation_precision_counts_only_supported_citations():
    evidence = [_evidence("E1"), _evidence("E2", verified=False),
                _evidence("E3", support="weak")]
    assert metrics.citation_precision(_bundle("x", evidence)) == pytest.approx(1 / 3)
    assert metrics.citation_precision(_bundle("x", [])) == 1.0


def test_citation_recall_measures_gold_coverage():
    evidence = [_evidence("E1", "a"), _evidence("E2", "b")]
    assert metrics.citation_recall(_bundle("x", evidence), ["a", "c"]) == 0.5
    assert metrics.citation_recall(_bundle("x", evidence), []) == 0.0


def test_relevance_requires_key_point_coverage():
    answer = "Hybrid retrieval improves recall at ten from 0.61 to 0.78."
    bundle = _bundle(answer, [])
    assert metrics.relevance(bundle, ["recall at ten", "0.78"]) == 1.0
    assert metrics.relevance(bundle, ["battery life"]) == 0.0


def test_hallucination_rate_and_counts():
    answer = ("- Hybrid retrieval improves recall at ten substantially. [E1]\n"
              "- Reranking reduces median latency to seventy milliseconds. [E2]")
    bundle = _bundle(answer, [_evidence("E1"), _evidence("E2")],
                     unsupported=["Reranking reduces median latency to seventy "
                                  "milliseconds. [E2]"])
    rate, unsupported, claims = metrics.hallucination_rate(bundle)
    assert (unsupported, claims) == (1, 2)
    assert rate == 0.5
    assert metrics.hallucination_rate(_bundle("", [])) == (0.0, 0, 0)


def test_evaluate_answer_bundles_the_metric_set():
    evidence = [_evidence("E1", "d1")]
    bundle = _bundle("- Retrieval fusion improves recall at ten. [E1]", evidence)
    result = metrics.evaluate_answer(bundle, gold_docs=["d1"], key_points=["recall at ten"])
    assert set(result.as_dict()) >= {"citation_precision", "citation_recall",
                                     "relevance", "hallucination_rate", "latency_ms"}
    assert result.citation_recall == 1.0


def test_aggregate_averages_numeric_columns():
    assert metrics.aggregate([{"a": 1.0}, {"a": 3.0}]) == {"a": 2.0}
    assert metrics.aggregate([]) == {}


# ------------------------------------------------------------------ judge
def test_judge_is_independent_of_the_system_flag(index):
    chunk = index.chunks()[0]
    evidence = [Evidence(evidence_id="E1", claim="x", quote=chunk.text[:100],
                         doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, title="t",
                         verified=False)]        # the system says "unverified"
    bundle = _bundle(f"- {chunk.text[:100]} [E1]", evidence)
    judgement = Judge(index).assess(bundle)
    assert judgement.citations_supported == 1     # the judge decides, not the flag
    assert judgement.citation_support == 1.0


def test_judge_flags_an_invented_claim(index):
    chunk = index.chunks()[0]
    evidence = [Evidence(evidence_id="E1", claim="x", quote=chunk.text[:100],
                         doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, title="t")]
    bundle = _bundle("- Zebrafish optogenetics tripled recall in our lab. [E1]", evidence)
    judgement = Judge(index).assess(bundle)
    assert judgement.claims_grounded == 0
    assert judgement.hallucination_rate == 1.0


# ------------------------------------------------------------------ baselines
def test_baselines_return_the_same_bundle_contract(index):
    for system in (ConventionalRAGSystem(index), SingleAgentSystem(index),
                   CoordinatorAgent(index)):
        bundle = system.answer("what is reciprocal rank fusion?")
        assert isinstance(bundle, AnswerBundle)
        assert bundle.system == system.name
        assert bundle.answer and bundle.latency_ms > 0


def test_conventional_rag_does_not_expand_or_rerank(index):
    bundle = ConventionalRAGSystem(index).answer("reciprocal rank fusion")
    stages = [stage["stage"] for stage in bundle.trace["events"][0]["payload"]["stages"]]
    assert "no-rerank" in stages
    assert bundle.notes


def test_single_agent_has_no_gap_agent_in_its_trace(index):
    bundle = SingleAgentSystem(index).answer("what are the limitations?")
    assert "gaps" not in bundle.trace["agents"]
    assert bundle.gaps == []


# ------------------------------------------------------------------ runner
def test_runner_records_one_row_per_system_and_question(results, dataset):
    assert len(results.results) == 3 * len(dataset)
    systems = {row.system for row in results.results}
    assert systems == {"conventional_rag", "single_agent", "multi_agent"}


def test_runner_summary_and_categories(results):
    summary = results.summary()
    assert set(summary) == {"conventional_rag", "single_agent", "multi_agent"}
    assert all(0.0 <= row["recall_at_k"] <= 1.0 for row in summary.values())
    by_category = results.by_category()
    assert set(by_category) == set(results.dataset.categories())


def test_runner_writes_jsonl_rows(tmp_path, index, dataset):
    runner = EvaluationRunner(dataset, k=5, log_dir=tmp_path / "logs", index=index)
    runner.run_system(SingleAgentSystem(index), name="single_agent", limit=3)
    log = tmp_path / "logs" / "evaluation_runs.jsonl"
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3
    assert lines[0]["system"] == "single_agent"
    assert "metrics" in lines[0] and "answer" in lines[0]


def test_runner_respects_the_limit(results):
    limited = [row for row in results.results if row.system == "multi_agent"]
    assert len(limited) == len(results.dataset)


# ------------------------------------------------------------------ statistics
def test_paired_bootstrap_detects_a_consistent_gain():
    baseline = [0.4] * 20
    treatment = [0.7] * 20
    difference, low, high, p_value = paired_bootstrap(baseline, treatment, samples=500)
    assert difference == pytest.approx(0.3)
    assert low > 0 and high > 0
    assert p_value < 0.05


def test_paired_bootstrap_finds_no_difference_for_identical_systems():
    values = [0.5, 0.6, 0.7, 0.8] * 5
    difference, _, _, p_value = paired_bootstrap(values, values, samples=500)
    assert difference == 0.0
    assert p_value == 1.0


def test_paired_bootstrap_is_deterministic_under_a_seed():
    baseline = [0.1, 0.2, 0.3, 0.4]
    treatment = [0.2, 0.25, 0.35, 0.5]
    assert paired_bootstrap(baseline, treatment, samples=300, seed=7) == \
        paired_bootstrap(baseline, treatment, samples=300, seed=7)


def test_paired_bootstrap_handles_empty_input():
    assert paired_bootstrap([], [], samples=10) == (0.0, 0.0, 0.0, 1.0)


def test_compare_systems_produces_a_row_per_metric(results):
    comparisons = compare_systems(results.results, baseline="conventional_rag",
                                  treatment="multi_agent", samples=500)
    assert comparisons
    assert {item.metric for item in comparisons} >= {"recall_at_k", "relevance",
                                                     "latency_ms"}
    for item in comparisons:
        assert item.samples == len(results.dataset)
        assert item.wins + item.losses + item.ties == item.samples
        assert 0 <= item.p_value <= 1
        assert item.verdict()


def test_compare_systems_with_no_shared_questions_returns_empty(results):
    assert compare_systems(results.results, baseline="nope", treatment="multi_agent") == []


def test_tables_render_markdown(results):
    summary = results.summary()
    table = markdown_table(summary)
    assert table.startswith("| Metric |")
    assert "conventional_rag" in table
    comparisons = compare_systems(results.results, baseline="conventional_rag",
                                  treatment="multi_agent", samples=200)
    table = comparison_table(comparisons)
    assert "95% CI" in table and "Significant" in table
    assert markdown_table({}) == "(no results)"
    assert comparison_table([]) == "(no comparisons)"


# ------------------------------------------------------------------ report
def test_metric_sanity_check_proves_the_detector_fires(index):
    rows = metric_sanity_check(index)
    faithful = next(row for row in rows if row["case"].startswith("faithful"))
    fabricated = next(row for row in rows if "fabricated" in row["case"])
    invented = next(row for row in rows if "invented" in row["case"])
    assert faithful["hallucination_rate"] == 0.0
    assert fabricated["hallucination_rate"] == 1.0
    assert invented["hallucination_rate"] == 1.0


def test_report_contains_every_required_section(index, tmp_path):
    text = build_report(index)
    for heading in ("## 1. Corpus and configuration", "## 2. Systems compared",
                    "## 3. Aggregate results", "## 4. Results by question category",
                    "## 5. Statistical comparison", "## 6. Metric sanity check",
                    "## 7. What the numbers say", "## 8. Threats to validity",
                    "## 9. Reproducing this report"):
        assert heading in text
    assert "multi_agent" in text and "conventional_rag" in text

    from scientific_llm.report import write_benchmark_report

    path = write_benchmark_report(index, out_path=tmp_path / "r.md")
    assert path.exists() and path.read_text(encoding="utf-8").startswith(
        "# Scientific RAG Benchmark Report")
