---
title: Section-Aware Chunking Improves Retrieval of Method and Limitation Statements
authors: P. Oduya, E. Bergstrom, N. Rahimi
year: 2021
venue: Journal of Scholarly Text Mining
doi: 10.1000/jstm.2021.0093
keywords: chunking, section awareness, passage retrieval, scientific text, segmentation
---

# Abstract

Fixed-length passage segmentation ignores the rhetorical structure of scientific
papers. We compare fixed windows of 256 tokens with section-aware chunks of 220
tokens, and find that section awareness improves recall of method statements by 0.12
and recall of limitation statements by 0.19, at equal index size.

# 1 Introduction

A sentence means something different depending on where it appears. In a methods
section it describes what was done; in a limitations section it describes what was
not done. Flattening a paper into a token stream destroys this signal, and retrieval
systems that flatten lose the ability to answer process and gap questions.

# 2 Background

Passage retrieval has traditionally used fixed windows with overlap. Dense retrievers
were trained on such windows, which biases them towards mid-section text, because
section boundaries produce short windows that are often discarded during training
data preparation.

# 3 Methods

We parse each paper into sections using heading recognition, mapping headings to
canonical labels: abstract, introduction, related work, background, methods, results,
discussion, limitations, future work and conclusion. Chunks never cross a section
boundary and are packed from whole paragraphs until a budget of 220 tokens is
reached, with 45 tokens of trailing-sentence overlap. We compare against fixed
windows of 256 tokens with 64 tokens of overlap on the same corpus of 400 papers,
with 1200 manually annotated queries, half of which target method statements and half
of which target limitations. We report recall at ten as the primary metric.

# 4 Results

Section-aware chunking improves recall at ten for method queries from 0.58 to 0.70 and
for limitation queries from 0.42 to 0.61. For factual queries the difference is
within noise, at 0.74 against 0.73. The index size is unchanged because both schemes
produce roughly the same number of chunks. The gain is largest for papers with long
method sections, where fixed windows frequently straddle a heading.

# 5 Discussion

The result is an argument for keeping structure at indexing time rather than trying
to recover it at query time. A section label is cheap to store and it gives the
retriever a prior that costs nothing to apply.

# 6 Limitations

Heading recognition fails on papers whose sections are unnumbered or whose PDF text
extraction merges headings into body text, which affected roughly 8 percent of the
corpus in our error analysis. We did not evaluate two-column layouts, where reading
order errors are common. The annotation scheme used one annotator per query, so
inter-annotator agreement for the gold labels is unmeasured.

# 7 Future Work

Future work should combine section priors with a learned reranker, and should study
whether layout-aware extraction removes the remaining heading errors.
