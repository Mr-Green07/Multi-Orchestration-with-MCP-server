---
title: Reproducibility of Retrieval Experiments: What Actually Breaks
authors: T. Iversen, C. Mbeki, O. Petrenko
year: 2022
venue: Journal of Empirical Software and Systems Research
doi: 10.1000/jessr.2022.0019
keywords: reproducibility, benchmarks, experimental setup, versioning, evaluation
---

# Abstract

We attempted to reproduce the reported results of 24 retrieval papers from released
code and data. Eleven reproduced within one point of the reported metric, seven
required a missing component to be reimplemented, and six could not be reproduced at
all. The most common single cause of divergence was an undocumented preprocessing
choice, followed by a changed corpus version.

# 1 Introduction

Reproducibility is a property of the whole pipeline, not of the model code. Retrieval
experiments depend on tokenisation, on the corpus snapshot, and on the evaluation
script, any of which can move a reported number by several points.

# 2 Related Work

Prior reproducibility studies in machine learning report similar failure rates and
identify missing hyperparameters as the main obstacle. Retrieval adds two further
sources of divergence: the index build and the relevance labels.

# 3 Methods

For each of 24 papers we ran the released code, then, where results did not match,
reimplemented the missing component with the description in the paper. We recorded
every divergence above one point in the primary reported metric and classified its
cause. We also recorded wall-clock time to a first successful run. All experiments
were run on identical hardware with a pinned Python version and a frozen dependency
lock file.

# 4 Results

Eleven papers reproduced within one point of the reported metric, seven reproduced
after a component was reimplemented, and six could not be reproduced. Preprocessing
differences caused four divergences, corpus version differences caused three, and
evaluation script differences caused two. Median time to a first successful run was
3.5 hours, with a long tail above twenty hours. Papers that shipped a frozen
dependency lock file reproduced nearly twice as often as those that did not.

# 5 Discussion

The cheapest intervention is a lock file plus a versioned corpus snapshot. Neither
requires extra compute, and both remove the two most common causes of divergence in
our sample.

# 6 Limitations

Our sample of 24 papers is small and drawn from two venues, so the failure rate is an
estimate with wide uncertainty. Papers that never released code were excluded, which
biases the sample towards better practice. We did not contact authors to ask about
undocumented choices, so some divergences classified as preprocessing differences may
have another cause. Hardware was held constant, so we cannot report on hardware-driven
variation.

# 7 Future Work

Future work should test whether containerised artefacts with a pinned corpus snapshot
close the remaining gap, and should track reproducibility rates over time.
