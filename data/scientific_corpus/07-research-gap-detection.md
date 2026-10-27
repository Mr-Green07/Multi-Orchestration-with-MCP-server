---
title: Detecting Research Gaps by Mining Limitation Statements
authors: K. Sandoval, H. Meyer, A. Gupta
year: 2024
venue: Journal of Automated Literature Analysis
doi: 10.1000/jala.2024.0012
keywords: research gaps, limitations, future work, literature analysis, novelty
---

# Abstract

Research gaps are usually identified by experts reading between the lines of a
literature. We show that a majority of explicit gap statements appear in limitation
and future-work sections and can be extracted with cue-phrase matching and
section-aware retrieval, reaching a precision of 0.74 on a manually labelled set of
600 sentences.

# 1 Introduction

A gap statement is a sentence that describes what the work does not do, cannot do, or
leaves for later. Such sentences are abundant but poorly served by general retrieval,
because they rarely repeat the terminology of the question that would need them.

# 2 Related Work

Prior work on future-work detection used citation context and syntactic patterns.
Work on scientific summarisation often excludes limitation sections on the grounds
that they are boilerplate, which removes exactly the sentences a gap analysis needs.

# 3 Methods

We define eleven cue phrases, including limitation, future work, we do not, remains,
unresolved and not evaluated, and extract candidate sentences from limitation, future
work and discussion sections. Candidates are ranked by term overlap with the question
and by a section prior that boosts limitation sections by eight percent. We also
report corpus-level gaps: question terms that no retrieved passage covers. Evaluation
uses 600 sentences from 150 papers, labelled by two annotators with agreement measured
by Cohen's kappa of 0.77.

# 4 Results

Cue-phrase matching reaches a precision of 0.74 and a recall of 0.66 for gap
sentences. Adding the section prior raises precision to 0.79. Corpus-level gap
reporting, which states that no retrieved passage discusses a query term, is correct
in 0.83 of flagged cases. The most common true gap categories are evaluation on a
single dataset, absence of a human evaluation, and missing comparison to a strong
baseline.

# 5 Discussion

Gap statements are formulaic, which is why cue matching works and why a learned
classifier offers limited additional value. The harder problem is aggregation: the
same gap appears in many papers and should be reported once, with several
citations.

# 6 Limitations

We do not deduplicate gaps across papers, so a repeated limitation is reported
multiple times. Cue matching misses implicit gaps stated as positive claims, such as
a method that only reports results on English data. Our annotators labelled sentences
in isolation, without the surrounding paragraph, which may have inflated agreement.
We did not evaluate whether the extracted gaps are actually novel to a researcher.

# 7 Future Work

Future work should cluster gap statements into themes, should test whether a language
model can rank gap novelty against a citation graph, and should measure whether
researchers find the reported gaps useful in a small user study.
