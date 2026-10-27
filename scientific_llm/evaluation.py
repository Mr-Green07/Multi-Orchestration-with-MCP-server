"""scientific_llm/evaluation.py
=============================
Benchmark dataset, evaluation runner and statistical comparison
(roadmap items 17, 20, 21, 22).

The benchmark is a JSON file of questions, each with:

* ``gold_docs``   - the paper ids that contain the answer;
* ``key_points``  - short phrases a correct answer must mention;
* ``category``    - factual / comparison / gap / methodology / multi_hop;
* ``notes``       - why the question is fair.

The runner is system-agnostic (anything with ``.answer(question)``), records one
JSONL row per (system, question), and aggregates into the table that the report
renders. Statistical comparison uses a **paired bootstrap** over questions: with
~20 questions a t-test's normality assumption is not credible, and a bootstrap
confidence interval on the *difference* is what a reviewer will ask for.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from scientific_llm import metrics as metrics_module
from scientific_llm.judge import Judge
from scientific_llm.models import AnswerBundle

DEFAULT_BENCHMARK_PATH = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "questions.json"


# --------------------------------------------------------------------------- dataset
@dataclass
class BenchmarkQuestion:
    question_id: str
    question: str
    gold_docs: list[str]
    key_points: list[str] = field(default_factory=list)
    category: str = "factual"
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> BenchmarkQuestion:
        question = str(payload.get("question", "")).strip()
        if not question:
            raise ValueError("a benchmark question needs 'question'")
        return cls(
            question_id=str(payload.get("id") or payload.get("question_id") or
                            f"q{abs(hash(question)) % 10_000:04d}"),
            question=question,
            gold_docs=[str(item) for item in payload.get("gold_docs", [])],
            key_points=[str(item) for item in payload.get("key_points", [])],
            category=str(payload.get("category", "factual")),
            notes=str(payload.get("notes", "")),
        )


class BenchmarkDataset:
    """A loaded, validated benchmark file."""

    def __init__(self, questions: list[BenchmarkQuestion], name: str = "benchmark") -> None:
        if not questions:
            raise ValueError("the benchmark has no questions")
        self.questions = questions
        self.name = name

    @classmethod
    def load(cls, path: str | Path | None = None) -> BenchmarkDataset:
        file_path = Path(path or DEFAULT_BENCHMARK_PATH)
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            name = str(payload.get("name") or file_path.stem)
            raw_questions = payload.get("questions") or []
        else:
            name, raw_questions = file_path.stem, payload
        questions = [BenchmarkQuestion.from_dict(item) for item in raw_questions]
        return cls(questions, name=name)

    def __len__(self) -> int:
        return len(self.questions)

    def __iter__(self):
        return iter(self.questions)

    def categories(self) -> list[str]:
        seen: list[str] = []
        for question in self.questions:
            if question.category not in seen:
                seen.append(question.category)
        return seen

    def gold_doc_ids(self) -> set[str]:
        return {doc_id for question in self.questions for doc_id in question.gold_docs}


def resolve_dataset(dataset: BenchmarkDataset, index) -> BenchmarkDataset:
    """Expand ``gold_docs`` prefixes into the real (hashed) document ids.

    The corpus files carry human-written gold prefixes so the benchmark stays
    readable; ids are content-addressed, so they are resolved against the live
    index at evaluation time.
    """
    available = [document.doc_id for document in index.documents()]
    resolved: list[BenchmarkQuestion] = []
    unresolved: list[str] = []
    for question in dataset.questions:
        gold: list[str] = []
        for prefix in question.gold_docs:
            matches = [doc_id for doc_id in available
                       if doc_id == prefix or doc_id.startswith(prefix)]
            if not matches:
                unresolved.append(prefix)
            gold.extend(matches)
        resolved.append(BenchmarkQuestion(
            question_id=question.question_id, question=question.question,
            gold_docs=sorted(set(gold)), key_points=question.key_points,
            category=question.category, notes=question.notes))
    if unresolved:
        raise ValueError("benchmark references unknown documents: "
                         + ", ".join(sorted(set(unresolved))))
    return BenchmarkDataset(resolved, name=dataset.name)


# --------------------------------------------------------------------------- runner
@dataclass
class QuestionResult:
    question_id: str
    question: str
    system: str
    category: str
    metrics: dict[str, float]
    answer: str
    citations: int
    gold_docs: list[str]
    retrieved_doc_ids: list[str]
    trace_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "question_id": self.question_id, "question": self.question,
            "system": self.system, "category": self.category,
            "metrics": self.metrics, "answer": self.answer,
            "citations": self.citations, "gold_docs": self.gold_docs,
            "retrieved_doc_ids": self.retrieved_doc_ids, "trace_id": self.trace_id,
        }


class EvaluationRunner:
    """Run every system over every question and collect the raw rows."""

    def __init__(self, dataset: BenchmarkDataset, k: int = 5,
                 log_dir: str | Path | None = None, index=None) -> None:
        self.dataset = dataset
        self.k = k
        self.log_dir = Path(log_dir) if log_dir else None
        self.index = index
        self.judge = Judge(index) if index is not None else None
        self.results: list[QuestionResult] = []

    def run_system(self, system, *, name: str | None = None,
                   limit: int | None = None) -> list[QuestionResult]:
        system_name = name or str(getattr(system, "name", type(system).__name__))
        rows: list[QuestionResult] = []
        questions = self.dataset.questions[:limit] if limit else self.dataset.questions
        for question in questions:
            started = time.perf_counter()
            bundle: AnswerBundle = system.answer(question.question)
            if bundle.latency_ms <= 0:
                bundle.latency_ms = (time.perf_counter() - started) * 1000.0
            answer_metrics = metrics_module.evaluate_answer(
                bundle, gold_docs=question.gold_docs, key_points=question.key_points)
            retrieved = bundle.retrieved_doc_ids
            answer_metrics_dict = answer_metrics.as_dict()
            if self.judge is not None:
                # Independent re-check: never trust a system's own citations.
                judgement = self.judge.assess(bundle)
                answer_metrics_dict.update({
                    "citation_support": round(judgement.citation_support, 4),
                    "groundedness": round(judgement.groundedness, 4),
                    "judged_hallucination_rate": round(judgement.hallucination_rate, 4),
                })
            answer_metrics_dict.update({
                "recall_at_k": round(metrics_module.recall_at_k(
                    retrieved, question.gold_docs, self.k), 4),
                "mrr": round(metrics_module.reciprocal_rank(retrieved, question.gold_docs), 4),
                "precision_at_k": round(metrics_module.precision_at_k(
                    retrieved, question.gold_docs, self.k), 4),
            })
            trace = bundle.trace or {}
            row = QuestionResult(
                question_id=question.question_id, question=question.question,
                system=system_name, category=question.category,
                metrics=answer_metrics_dict, answer=bundle.answer,
                citations=len(bundle.evidence),
                gold_docs=question.gold_docs, retrieved_doc_ids=retrieved,
                trace_id=str(trace.get("trace_id") or "") or None,
            )
            rows.append(row)
            self.results.append(row)
            if self.log_dir:
                self._log(row)
        return rows

    def run_all(self, systems: dict[str, object], *, limit: int | None = None
                ) -> list[QuestionResult]:
        for name, system in systems.items():
            self.run_system(system, name=name, limit=limit)
        return self.results

    def _log(self, row: QuestionResult) -> None:
        assert self.log_dir is not None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with (self.log_dir / "evaluation_runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row.as_dict(), ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ aggregation
    def summary(self, results: list[QuestionResult] | None = None) -> dict[str, dict]:
        rows = results if results is not None else self.results
        by_system: dict[str, list[dict[str, float]]] = {}
        for row in rows:
            by_system.setdefault(row.system, []).append(row.metrics)
        return {system: metrics_module.aggregate(values)
                for system, values in by_system.items()}

    def by_category(self, results: list[QuestionResult] | None = None) -> dict[str, dict]:
        rows = results if results is not None else self.results
        grouped: dict[str, dict[str, list[dict[str, float]]]] = {}
        for row in rows:
            grouped.setdefault(row.category, {}).setdefault(row.system, []).append(row.metrics)
        return {
            category: {system: metrics_module.aggregate(values)
                       for system, values in systems.items()}
            for category, systems in grouped.items()
        }


# --------------------------------------------------------------------------- statistics
@dataclass
class ComparisonResult:
    metric: str
    baseline: str
    treatment: str
    baseline_mean: float
    treatment_mean: float
    difference: float
    ci_low: float
    ci_high: float
    wins: int
    losses: int
    ties: int
    samples: int
    p_value: float
    significant: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric, "baseline": self.baseline,
            "treatment": self.treatment,
            "baseline_mean": round(self.baseline_mean, 4),
            "treatment_mean": round(self.treatment_mean, 4),
            "difference": round(self.difference, 4),
            "ci95": [round(self.ci_low, 4), round(self.ci_high, 4)],
            "wins": self.wins, "losses": self.losses, "ties": self.ties,
            "samples": self.samples, "p_value": round(self.p_value, 4),
            "significant": self.significant,
        }

    def verdict(self) -> str:
        if abs(self.difference) < 0.0005:
            return (f"{self.treatment} and {self.baseline} are indistinguishable on "
                    f"{self.metric} (difference rounds to 0.000)")
        direction = "higher" if self.difference > 0 else "lower"
        interval = f"95% CI [{self.ci_low:+.3f}, {self.ci_high:+.3f}]"
        if not self.significant:
            return (f"{self.treatment} is {direction} than {self.baseline} on {self.metric} "
                    f"by {self.difference:+.3f} ({interval}, p={self.p_value:.3f}) "
                    f"- not significant")
        return (f"{self.treatment} is significantly {direction} than {self.baseline} on "
                f"{self.metric}: {self.difference:+.3f} ({interval}, p={self.p_value:.3f})")


def paired_bootstrap(baseline: list[float], treatment: list[float], *,
                     samples: int = 2000, alpha: float = 0.05,
                     seed: int = 1234) -> tuple[float, float, float, float]:
    """Bootstrap the mean difference; returns (diff, low, high, p_value).

    ``p_value`` is the two-sided bootstrap p: the share of resampled differences
    that fall on the opposite side of zero, doubled and capped at 1.
    """
    size = min(len(baseline), len(treatment))
    if size == 0:
        return 0.0, 0.0, 0.0, 1.0
    baseline, treatment = baseline[:size], treatment[:size]
    differences = [treatment[index] - baseline[index] for index in range(size)]
    observed = sum(differences) / size

    generator = random.Random(seed)
    means: list[float] = []
    for _ in range(samples):
        total = 0.0
        for _ in range(size):
            total += differences[generator.randrange(size)]
        means.append(total / size)
    means.sort()
    low = means[int((alpha / 2) * len(means))]
    high = means[min(len(means) - 1, int((1 - alpha / 2) * len(means)))]

    # Two-sided bootstrap p: twice the smaller tail probability around zero.
    at_or_below = sum(1 for value in means if value <= 0) / len(means)
    at_or_above = sum(1 for value in means if value >= 0) / len(means)
    p_value = min(1.0, 2 * min(at_or_below, at_or_above))
    return observed, low, high, p_value


def compare_systems(results: list[QuestionResult], *, baseline: str, treatment: str,
                    metrics: list[str] | None = None,
                    samples: int = 2000) -> list[ComparisonResult]:
    """Per-metric paired comparison of two systems over the same questions."""
    metrics = metrics or ["recall_at_k", "mrr", "citation_precision", "relevance",
                          "hallucination_rate", "latency_ms"]
    baseline_rows = {row.question_id: row for row in results if row.system == baseline}
    treatment_rows = {row.question_id: row for row in results if row.system == treatment}
    shared = sorted(set(baseline_rows) & set(treatment_rows))
    comparisons: list[ComparisonResult] = []

    for metric in metrics:
        left = [float(baseline_rows[qid].metrics.get(metric, 0.0)) for qid in shared]
        right = [float(treatment_rows[qid].metrics.get(metric, 0.0)) for qid in shared]
        if not left:
            continue
        difference, low, high, p_value = paired_bootstrap(left, right, samples=samples)
        wins = sum(1 for a, b in zip(left, right, strict=False) if b > a)
        losses = sum(1 for a, b in zip(left, right, strict=False) if b < a)
        ties = len(shared) - wins - losses
        comparisons.append(ComparisonResult(
            metric=metric, baseline=baseline, treatment=treatment,
            baseline_mean=sum(left) / len(left), treatment_mean=sum(right) / len(right),
            difference=difference, ci_low=low, ci_high=high,
            wins=wins, losses=losses, ties=ties, samples=len(shared),
            p_value=p_value, significant=p_value < 0.05,
        ))
    return comparisons


# --------------------------------------------------------------------------- report
def markdown_table(summary: dict[str, dict], columns: list[str] | None = None) -> str:
    """Render the aggregate table used by the benchmark report and the CLI."""
    if not summary:
        return "(no results)"
    systems = list(summary)
    columns = columns or [key for key in summary[systems[0]]
                          if key not in {"answer_length"}]
    header = "| Metric | " + " | ".join(systems) + " |"
    separator = "| --- | " + " | ".join("---" for _ in systems) + " |"
    lines = [header, separator]
    for column in columns:
        cells = []
        for system in systems:
            value = summary[system].get(column, 0.0)
            cells.append(f"{value:.3f}" if isinstance(value, float) else str(value))
        lines.append(f"| {column} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def comparison_table(comparisons: list[ComparisonResult]) -> str:
    if not comparisons:
        return "(no comparisons)"
    lines = ["| Metric | Baseline | Treatment | Δ | 95% CI | p | Significant | W/L/T |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for item in comparisons:
        lines.append(
            f"| {item.metric} | {item.baseline_mean:.3f} | {item.treatment_mean:.3f} | "
            f"{item.difference:+.3f} | [{item.ci_low:+.3f}, {item.ci_high:+.3f}] | "
            f"{item.p_value:.3f} | {'yes' if item.significant else 'no'} | "
            f"{item.wins}/{item.losses}/{item.ties} |")
    return "\n".join(lines)
