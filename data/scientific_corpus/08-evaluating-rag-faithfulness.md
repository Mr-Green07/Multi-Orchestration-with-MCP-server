---
title: Evaluating Faithfulness in Retrieval-Augmented Generation: Metrics and Pitfalls
authors: J. Whitmore, F. Duarte, S. Kaur
year: 2022
venue: Journal of Language Model Evaluation
doi: 10.1000/jlme.2022.0077
keywords: evaluation, faithfulness, hallucination, metrics, benchmark
---

# Abstract

Faithfulness metrics for retrieval-augmented generation are often reported without
stating what they measure. We separate three quantities: whether a citation exists,
whether the cited passage is relevant, and whether the passage supports the claim. On
a re-annotation of two public benchmarks we find that the first two are widely
reported and nearly saturated, while support is rarely measured and varies by 34
points across systems.

# 1 Introduction

A benchmark that rewards citation existence can be satisfied by citing any retrieved
document. Evaluation practice therefore shapes system behaviour: systems optimise the
metric that is measured, and an easy metric produces citations that are present but
unhelpful.

# 2 Related Work

Automatic faithfulness measures include entailment scoring with a separate model,
token overlap between claim and source, and human annotation. Each has a different
failure mode: entailment models are expensive and can be fooled by negation, overlap
is cheap and insensitive to word order, and human annotation does not scale.

# 3 Methods

We define citation existence as the share of claims carrying at least one reference to
a retrieved document. Relevance is measured by asking whether the cited document was
in the gold set for the question. Support is measured by token overlap between claim
and quotation with a threshold of 0.45, validated against human labels. We re-annotate
two public benchmarks with 400 answers each and compare reported numbers against our
own measurements. We also report latency, because support checking costs an extra
comparison per citation.

# 4 Results

Citation existence is above 0.95 for every system we examined, and relevance ranges
from 0.55 to 0.81. Support ranges from 0.41 to 0.75, a spread of 34 points, and it
correlates weakly with relevance at a correlation of 0.38. Systems that call a
separate validator before answering report the highest support. Token overlap agrees
with human labels on 0.87 of citations, while a sentence-level entailment model
agrees on 0.83 and costs forty times more.

# 5 Discussion

Reporting support alongside relevance is the single most informative change to an
evaluation table. It is also the metric most likely to be gamed by quoting a long
passage that contains the claim's words without supporting it, which is why a
verbatim check should be paired with a coverage threshold.

# 6 Limitations

Token-overlap support is insensitive to negation and to claims that require combining
two sentences. Our re-annotation covers two benchmarks and four systems, so the
correlation estimates are noisy. We did not evaluate multilingual answers, and the
human annotators were graduate students in one lab, which limits annotator diversity.

# 7 Conclusion

Evaluation should report support, not only existence and relevance, and should state
the threshold and the agreement of any automatic proxy with human labels.
