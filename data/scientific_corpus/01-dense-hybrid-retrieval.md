---
title: Dense and Hybrid Retrieval for Scientific Question Answering
authors: A. Raman, K. Lindqvist, M. Osei
year: 2022
venue: Journal of Information Retrieval Systems
doi: 10.1000/jirs.2022.0042
keywords: dense retrieval, hybrid retrieval, BM25, bi-encoder, scientific QA
---

# Abstract

Scientific question answering requires retrieving passages from a large, unevenly
written corpus. We compare sparse lexical retrieval, dense bi-encoder retrieval, and
a hybrid that fuses both ranked lists with reciprocal rank fusion. On a benchmark of
two thousand questions over open-access papers, hybrid retrieval improves recall at
ten from 0.61 to 0.78 over BM25 alone and from 0.66 to 0.78 over the dense model
alone. We find that the benefit of fusion is largest for questions containing rare
domain terminology, where the bi-encoder's learned representation is under-trained.

# 1 Introduction

Retrieval is the first decision in any retrieval-augmented pipeline, and it is the
decision that is hardest to fix downstream: no generator can cite a passage that was
never returned. Prior work in the biomedical setting established that dense
representations handle paraphrase well but degrade on identifiers, chemical names and
gene symbols, which are exactly the tokens a scientist types.

# 2 Related Work

Okapi BM25 remains a strong baseline after three decades because its term weighting
is robust to corpus size. Bi-encoders trained on natural questions learn a semantic
space in which question and passage are close, but they require substantial in-domain
training pairs. Reciprocal rank fusion combines ranked lists without score
calibration and is therefore attractive when the two retrievers produce scores on
incomparable scales.

# 3 Methods

We index each paper at section granularity. Chunks are constructed so that they never
cross a section boundary, with a target length of 220 tokens and an overlap of 45
tokens. Sparse retrieval uses BM25 with k1 equal to 1.5 and b equal to 0.75. Dense
retrieval uses a bi-encoder fine-tuned on SciDocs. Hybrid retrieval fuses the two
ranked lists with reciprocal rank fusion using a weight of 1.0 for the lexical list
and 0.8 for the dense list. We evaluate on the SciQA open benchmark, which contains
2000 question and answer pairs with gold passage annotations. We measure recall at k
for k in five, ten and twenty, and mean reciprocal rank.

# 4 Results

Hybrid fusion reaches recall at ten of 0.78, compared with 0.61 for BM25 and 0.66 for
the dense retriever. Mean reciprocal rank improves from 0.44 to 0.57. The fusion
gains are concentrated in questions that contain a rare term: on the subset of
questions where at least one token occurs in fewer than one hundred passages, the
hybrid improves recall at ten by 0.21 relative to the dense model, while on the
common-vocabulary subset the improvement is only 0.04. Latency increases from 18 ms
for BM25 to 41 ms for the hybrid, which remains well below the cost of generation.

# 5 Discussion

The results suggest that sparse and dense signals are complementary rather than
redundant. Fusion is not a free lunch: it doubles the number of candidates that must
be scored and it complicates failure analysis, because a missing passage can be
missing from either list.

# 6 Limitations

We do not evaluate on questions that require aggregating facts across multiple
papers, and the corpus is restricted to open-access publications, which biases the
venue distribution. Our dense model was fine-tuned on scientific text; results on
general-domain corpora may differ. We did not measure the effect of chunk size
systematically, so the 220-token setting may not transfer to papers with unusually
long method sections.

# 7 Conclusion

Hybrid retrieval with reciprocal rank fusion is a strong, cheap default for
scientific retrieval, and it should be the baseline against which learned rerankers
are compared.
