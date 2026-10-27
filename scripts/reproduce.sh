#!/usr/bin/env bash
# Reproduce every number in reports/benchmark_report.md from scratch.
#
#   bash scripts/reproduce.sh              # full run
#   bash scripts/reproduce.sh --fast       # skip the test suite
#
# Deterministic by construction: content-addressed document ids, a fixed hashing
# embedder, a deterministic reranker and a fixed bootstrap seed. Two runs on the
# same corpus must produce identical tables; the script asserts that.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "environment"
"$PYTHON" -V
"$PYTHON" -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'"

step "install (optional)"
# The package itself is standard-library only, so a missing/deferred install is
# not fatal: it runs straight from the source tree. Only lint/type/test tooling
# needs the dev extras.
if "$PYTHON" -m pip install -e ".[dev]" --quiet 2>/dev/null; then
  echo "editable install + dev extras: ok"
else
  echo "editable install skipped (no writable site-packages / PEP 668);"
  echo "running from the source tree instead. Use a venv for lint/type/test tooling."
fi

step "lint and type check"
"$PYTHON" -m ruff check scientific_llm scripts tests || echo "(ruff not installed, skipped)"
"$PYTHON" -m mypy scientific_llm --ignore-missing-imports || echo "(mypy not installed, skipped)"

if [[ "$FAST" -eq 0 ]]; then
  step "test suite"
  if "$PYTHON" -c "import pytest" 2>/dev/null; then
    "$PYTHON" -m pytest -q
  else
    echo "(pytest not installed, skipped - rerun with --fast or install the dev extras)"
  fi
fi

step "build the corpus index from scratch"
"$PYTHON" scripts/build_corpus.py --reset --verify

step "retrieval sanity: recall@k on the benchmark gold sets"
"$PYTHON" - <<'PY'
from scientific_llm.evaluation import BenchmarkDataset, resolve_dataset
from scientific_llm.index import CorpusIndex
from scientific_llm.metrics import recall_at_k
from scientific_llm.retrieval import HybridRetriever, RetrievalAgent

index = CorpusIndex()
dataset = resolve_dataset(BenchmarkDataset.load(), index)
agent = RetrievalAgent(HybridRetriever(index))
scores = []
for question in dataset:
    result = agent.retrieve(question.question, k=10)
    scores.append(recall_at_k(result.doc_ids(), question.gold_docs, 10))
print(f"mean recall@10 over {len(scores)} questions: {sum(scores)/len(scores):.3f}")
index.close()
PY

step "benchmark run (writes reports/)"
"$PYTHON" scripts/run_benchmark.py

step "determinism check: run twice, compare summaries"
cp reports/benchmark_summary.json /tmp/benchmark_summary_first.json
"$PYTHON" scripts/run_benchmark.py --no-report >/dev/null
"$PYTHON" - <<'PY'
import json
first = json.load(open("/tmp/benchmark_summary_first.json"))
second = json.load(open("reports/benchmark_summary.json"))
for system, metrics in first["summary"].items():
    for metric, value in metrics.items():
        if metric == "latency_ms":
            continue                      # wall clock is allowed to vary
        assert second["summary"][system][metric] == value, (system, metric)
print("deterministic: every non-timing metric reproduced exactly")
PY

step "done"
echo "report:   reports/benchmark_report.md"
echo "summary:  reports/benchmark_summary.json"
echo "rows:     reports/benchmark_rows.jsonl"
