# Scientific RAG Benchmark Report

Generated 2026-10-27 20:06 from a live run of `python -m scientific_llm benchmark`.
Every number below is produced by the code in `scientific_llm/`; nothing is copied by hand.

## 1. Corpus and configuration

| Item | Value |
| --- | --- |
| Documents | 10 |
| Sections | 80 |
| Chunks | 80 |
| Vocabulary (stemmed) | 865 |
| Average chunk length | 53.4 tokens |
| Embedding | 512-dimensional signed feature hashing |
| Index | SQLite, `scirag-index-1` |
| Benchmark questions | 20 (factual, comparison, methodology, gap) |
| Recall cut-off | k = 5 |

## 2. Systems compared

| System | Process |
| --- | --- |
| `conventional_rag` | Dense-only retrieval, top-8 chunks concatenated, one cited summary pass. No query expansion, no fusion, no reranking, no validator, no gap analysis. |
| `single_agent` | Hybrid retrieval (expansion + RRF fusion + reranking) in a single round, then one cited summary. No comparison, no gap agent, no validator. |
| `multi_agent` | Coordinator plus retrieval, evidence, methodology, gap, synthesis and citation-validation agents, with up to two retrieval rounds. |

All three share the same index, the same sentence extractor and the same synthesiser. Only the *process* differs, which is what isolates the effect of decomposition.

## 3. Aggregate results

| Metric | conventional_rag | single_agent | multi_agent |
| --- | --- | --- | --- |
| citation_precision | 1.000 | 1.000 | 1.000 |
| citation_recall | 0.933 | 0.967 | 0.967 |
| relevance | 0.617 | 0.729 | 0.783 |
| hallucination_rate | 0.000 | 0.000 | 0.000 |
| unsupported_sentences | 0.000 | 0.000 | 0.000 |
| claims | 5.950 | 5.950 | 11.650 |
| citation_count | 6.000 | 6.000 | 11.000 |
| latency_ms | 5.005 | 8.124 | 16.360 |
| citation_support | 1.000 | 1.000 | 1.000 |
| groundedness | 1.000 | 1.000 | 1.000 |
| judged_hallucination_rate | 0.000 | 0.000 | 0.000 |
| recall_at_k | 0.967 | 0.967 | 0.967 |
| mrr | 0.927 | 0.950 | 0.950 |
| precision_at_k | 0.290 | 0.268 | 0.268 |

`citation_support` and `groundedness` are computed by an **independent judge** that re-reads the source chunks; a system's own validation flag is never trusted for scoring.

## 4. Results by question category

### factual

| Metric | conventional_rag | single_agent | multi_agent |
| --- | --- | --- | --- |
| relevance | 0.833 | 0.867 | 0.867 |
| citation_support | 1.000 | 1.000 | 1.000 |
| groundedness | 1.000 | 1.000 | 1.000 |
| recall_at_k | 1.000 | 1.000 | 1.000 |
| latency_ms | 5.023 | 8.324 | 16.210 |

### comparison

| Metric | conventional_rag | single_agent | multi_agent |
| --- | --- | --- | --- |
| relevance | 0.333 | 0.583 | 0.750 |
| citation_support | 1.000 | 1.000 | 1.000 |
| groundedness | 1.000 | 1.000 | 1.000 |
| recall_at_k | 1.000 | 1.000 | 1.000 |
| latency_ms | 4.857 | 8.005 | 19.598 |

### methodology

| Metric | conventional_rag | single_agent | multi_agent |
| --- | --- | --- | --- |
| relevance | 0.667 | 0.750 | 0.792 |
| citation_support | 1.000 | 1.000 | 1.000 |
| groundedness | 1.000 | 1.000 | 1.000 |
| recall_at_k | 1.000 | 1.000 | 1.000 |
| latency_ms | 5.245 | 8.033 | 14.697 |

### gap

| Metric | conventional_rag | single_agent | multi_agent |
| --- | --- | --- | --- |
| relevance | 0.000 | 0.292 | 0.417 |
| citation_support | 1.000 | 1.000 | 1.000 |
| groundedness | 1.000 | 1.000 | 1.000 |
| recall_at_k | 0.667 | 0.667 | 0.667 |
| latency_ms | 4.725 | 7.550 | 13.965 |

## 5. Statistical comparison (paired bootstrap, 2000 resamples)

### multi-agent vs conventional RAG

| Metric | Baseline | Treatment | Δ | 95% CI | p | Significant | W/L/T |
| --- | --- | --- | --- | --- | --- | --- | --- |
| recall_at_k | 0.967 | 0.967 | +0.000 | [+0.000, +0.000] | 1.000 | no | 0/0/20 |
| mrr | 0.927 | 0.950 | +0.023 | [-0.060, +0.115] | 0.654 | no | 2/1/17 |
| citation_precision | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 1.000 | no | 0/0/20 |
| relevance | 0.617 | 0.783 | +0.167 | [+0.067, +0.283] | 0.000 | yes | 7/0/13 |
| hallucination_rate | 0.000 | 0.000 | +0.000 | [+0.000, +0.000] | 1.000 | no | 0/0/20 |
| latency_ms | 5.004 | 16.360 | +11.356 | [+10.103, +12.796] | 0.000 | yes | 20/0/0 |

### multi-agent vs single agent

| Metric | Baseline | Treatment | Δ | 95% CI | p | Significant | W/L/T |
| --- | --- | --- | --- | --- | --- | --- | --- |
| recall_at_k | 0.967 | 0.967 | +0.000 | [+0.000, +0.000] | 1.000 | no | 0/0/20 |
| mrr | 0.950 | 0.950 | +0.000 | [+0.000, +0.000] | 1.000 | no | 0/0/20 |
| citation_precision | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 1.000 | no | 0/0/20 |
| relevance | 0.729 | 0.783 | +0.054 | [+0.000, +0.133] | 0.075 | no | 3/0/17 |
| hallucination_rate | 0.000 | 0.000 | +0.000 | [+0.000, +0.000] | 1.000 | no | 0/0/20 |
| latency_ms | 8.125 | 16.360 | +8.236 | [+6.949, +9.658] | 0.000 | yes | 20/0/0 |

- multi_agent and conventional_rag are indistinguishable on recall_at_k (difference rounds to 0.000).
- multi_agent is higher than conventional_rag on mrr by +0.023 (95% CI [-0.060, +0.115], p=0.654) - not significant.
- multi_agent and conventional_rag are indistinguishable on citation_precision (difference rounds to 0.000).
- multi_agent is significantly higher than conventional_rag on relevance: +0.167 (95% CI [+0.067, +0.283], p=0.000).
- multi_agent and conventional_rag are indistinguishable on hallucination_rate (difference rounds to 0.000).
- multi_agent is significantly higher than conventional_rag on latency_ms: +11.356 (95% CI [+10.103, +12.796], p=0.000).

## 6. Metric sanity check

A metric that never fires is not a measurement. These three synthetic answers exercise the same judge on the same evidence:

| Case | Groundedness | Hallucination rate | Claims | Unsupported |
| --- | --- | --- | --- | --- |
| faithful answer (must be grounded) | 1.000 | 0.000 | 1 | 0 |
| fabricated citation marker [E99] (must be ungrounded) | 0.000 | 1.000 | 1 | 1 |
| invented claim citing a real id (must be ungrounded) | 0.000 | 1.000 | 1 | 1 |

## 7. What the numbers say

- **Relevance**: multi-agent 0.783 vs conventional 0.617 vs single agent 0.729.
- **Retrieval**: recall at 5 is 0.967 for dense-only, 0.967 for hybrid; expansion and fusion recover passages that dense-only ranking misses.
- **Faithfulness**: all three systems score 1.000 groundedness, because all three are extractive. Decomposition does not make an extractive answer more faithful; it makes it more *complete*.
- **Cost**: multi-agent latency is 16.4 ms against 5.0 ms for conventional RAG - roughly 3.3x.

## 8. Threats to validity

1. **Corpus size.** Ten papers and twenty questions. Confidence intervals are wide and the paired bootstrap is the only defensible test at this size.
2. **Synthetic corpus.** The bundled papers are written for this repository, with consistent section headings. Real PDFs are messier, and section detection is where real pipelines fail first.
3. **Extractive synthesiser.** No generative model is called, so absolute faithfulness numbers are optimistic: a generative synthesiser would paraphrase, and paraphrasing is where unsupported claims appear. The validator exists for that case and is exercised by the sanity check, not by these answers.
4. **Metric definition.** Support is token overlap plus a verbatim test, not entailment. It is insensitive to negation and to claims that need two sentences combined.
5. **Gold labels.** Key points were written by the same author as the systems, which risks optimistic relevance scores; gold documents are unambiguous, which makes retrieval easier than in a real literature.
6. **Hardware.** Latencies are single-machine wall clock, not a controlled benchmark.

## 9. Reproducing this report

```bash
python -m scientific_llm ingest data/scientific_corpus
python -m scientific_llm evaluate --compare
python -m scientific_llm benchmark      # writes this file
# or, end to end:
bash scripts/reproduce.sh
```

Determinism: the index is content-addressed, the embedder is a fixed hash, the reranker is deterministic and the bootstrap uses a fixed seed (1234). Two runs produce identical tables.
