#!/usr/bin/env python3
"""Run the three systems over the benchmark and write machine-readable results.

    python scripts/run_benchmark.py                       # default corpus + benchmark
    python scripts/run_benchmark.py --db /tmp/x.db --out reports/
    python scripts/run_benchmark.py --systems multi_agent single_agent

Outputs (in ``--out``, default ``reports/``):

* ``benchmark_summary.json``   - aggregate + per-category metrics
* ``benchmark_rows.jsonl``     - one line per (system, question)
* ``benchmark_report.md``      - the human-readable report (same generator as the CLI)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scientific_llm.agents import CoordinatorAgent  # noqa: E402
from scientific_llm.baselines import ConventionalRAGSystem, SingleAgentSystem  # noqa: E402
from scientific_llm.evaluation import (  # noqa: E402
    BenchmarkDataset,
    EvaluationRunner,
    resolve_dataset,
)
from scientific_llm.index import DEFAULT_DB_PATH, CorpusIndex  # noqa: E402
from scientific_llm.report import write_benchmark_report  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run the scientific RAG benchmark")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--out", default=str(REPORT_DIR))
    parser.add_argument("--systems", nargs="*", default=None)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = CorpusIndex(args.db)
    stats = index.stats()
    if not stats["documents"]:
        print("error: the index is empty - run scripts/build_corpus.py first",
              file=sys.stderr)
        index.close()
        return 1

    dataset = resolve_dataset(BenchmarkDataset.load(args.benchmark), index)
    available = {
        "conventional_rag": lambda: ConventionalRAGSystem(index),
        "single_agent": lambda: SingleAgentSystem(index),
        "multi_agent": lambda: CoordinatorAgent(index),
    }
    names = args.systems or list(available)
    unknown = [name for name in names if name not in available]
    if unknown:
        print(f"error: unknown systems {unknown}", file=sys.stderr)
        index.close()
        return 2

    runner = EvaluationRunner(dataset, k=args.k, index=index)
    runner.run_all({name: available[name]() for name in names}, limit=args.limit)

    summary = runner.summary()
    (out / "benchmark_summary.json").write_text(
        json.dumps({"corpus": stats, "summary": summary,
                    "by_category": runner.by_category()}, indent=2), encoding="utf-8")
    with (out / "benchmark_rows.jsonl").open("w", encoding="utf-8") as handle:
        for row in runner.results:
            handle.write(json.dumps(row.as_dict(), ensure_ascii=False) + "\n")

    print(json.dumps(summary, indent=2))
    print(f"\nrows:    {out / 'benchmark_rows.jsonl'} ({len(runner.results)} rows)")
    print(f"summary: {out / 'benchmark_summary.json'}")

    if not args.no_report:
        path = write_benchmark_report(index, out_path=out / "benchmark_report.md",
                                      benchmark_path=args.benchmark, k=args.k)
        print(f"report:  {path}")
    index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
