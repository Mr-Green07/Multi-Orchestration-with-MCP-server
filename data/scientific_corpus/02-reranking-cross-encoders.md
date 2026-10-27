---
title: Cross-Encoder Reranking Under a Latency Budget
authors: S. Petrova, D. Whitfield
year: 2023
venue: Proceedings of the Conference on Applied Retrieval
doi: 10.1000/car.2023.0117
keywords: reranking, cross-encoder, latency, cascade, precision
---

# Abstract

Reranking improves the precision of retrieval, but a cross-encoder that scores every
candidate is too slow for interactive use. We study cascaded reranking, in which a
cheap lexical scorer prunes the candidate set and a cross-encoder rescores only the
survivors. Pruning to forty candidates retains 96 percent of the recall of full
reranking while reducing median latency from 310 ms to 74 ms.

# 1 Introduction

A two-stage retriever is the standard architecture: a recall-oriented first stage
returns a candidate pool, and a precision-oriented second stage reorders it. The
second stage is usually a cross-encoder that reads the question and the passage
jointly, which is accurate and expensive.

# 2 Related Work

Prior studies report gains of four to nine points in precision at five from
cross-encoder reranking, with latency proportional to the number of scored pairs.
Cascade designs borrow from learning-to-rank practice, where a cheap model filters
before an expensive one.

# 3 Methods

We use the same BM25 first stage throughout. The cross-encoder is a six-layer
transformer trained on question and passage pairs with a binary relevance objective.
We vary the pruning depth in the set ten, twenty, forty, eighty and all candidates,
and we measure precision at five, recall at twenty and end-to-end latency on a single
CPU core. The evaluation corpus is the same 2000-question benchmark used in
scientific retrieval studies, with gold passage annotations.

# 4 Results

Full reranking achieves precision at five of 0.71 at a median latency of 310 ms.
Pruning to forty candidates achieves precision at five of 0.70 at 74 ms. Pruning to
ten candidates drops precision to 0.63, a loss that is visible to users. Recall at
twenty is essentially unchanged down to a pruning depth of forty, which indicates
that the first stage is not the bottleneck in that regime. The latency budget that
matters in practice is roughly one hundred milliseconds, and the forty-candidate
cascade fits inside it.

# 5 Discussion

The useful operating point depends on the first stage's recall profile, not on the
reranker's accuracy alone. If the first stage is weak, aggressive pruning removes
the passages the reranker would have rescued.

# 6 Limitations

We evaluate on a single CPU core and a single corpus, and we do not study batched
inference, which changes the cost model substantially on a GPU. Our cross-encoder was
trained on scientific pairs, so the transfer to legal or biomedical text is untested.
We do not report the effect of passage length on reranker latency, although longer
passages clearly cost more.

# 7 Future Work

Future work should study adaptive pruning that depends on the question's predicted
difficulty, and should measure whether a distilled reranker can match the cascade at
a quarter of the cost.
