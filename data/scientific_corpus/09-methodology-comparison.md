---
title: Comparing Methodologies Across Papers: A Structured Extraction Study
authors: G. Amari, B. Novak
year: 2023
venue: Journal of Research Analytics
doi: 10.1000/jra.2023.0064
keywords: methodology comparison, information extraction, datasets, metrics, reproducibility
---

# Abstract

Comparing methods across papers is difficult because datasets, metrics and reported
numbers are described in prose. We extract a four-field record for each paper -
method, dataset, metric and reported result - with cue-phrase extraction, and find
that 68 percent of records can be populated with no error on a set of 200 papers.

# 1 Introduction

A reader asking which of three retrieval methods is better needs four facts per
paper. Surveys compile these facts manually at high cost and low refresh rate.
Structured extraction is a cheaper route if the extracted fields can be validated
against the source sentence.

# 2 Related Work

Extraction of experimental settings has been studied as a slot-filling task over
method sections, with results strongly dependent on section detection quality.
Comparisons across papers are complicated by differing evaluation splits and by
reporting medians where others report means.

# 3 Methods

For each paper we detect methods and results sections, then extract the first
sentence matching a method cue, a dataset cue, a metric cue, and any sentence
containing a number with a percent sign. Extracted fields are stored with the source
sentence so a reader can verify them. We evaluate on 200 papers from a retrieval
venue, with a gold record per paper produced by two annotators. We report field-level
accuracy and the share of records with all four fields correct.

# 4 Results

Method extraction reaches 0.81 accuracy and dataset extraction 0.76. Metric extraction
reaches 0.88 because metric names are a closed vocabulary in this venue. Reported
result extraction reaches 0.71, with most errors caused by papers that report several
numbers in one sentence. The share of records with all four fields correct is 0.68.
Records without a source sentence are never emitted, which makes every error auditable.

# 5 Discussion

The closed-vocabulary fields are easy and the open-vocabulary field is hard, which
suggests that comparison tables are best built around a fixed metric vocabulary, with
free-text results attached rather than parsed.

# 6 Limitations

We evaluate on a single venue, so the method vocabulary is narrow. Papers that report
results in tables lose their numbers during text extraction, which is a systematic
failure for a subset of our corpus. We did not evaluate extraction from figures, and
we did not measure whether automated records change a reader's conclusion.

# 7 Future Work

Future work should combine text extraction with table extraction, and should test
whether a comparison record with provenance reduces the time a reader needs to reach
a decision.
