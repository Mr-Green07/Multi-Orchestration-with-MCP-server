---
title: Multi-Agent Decomposition for Retrieval-Augmented Question Answering
authors: L. Fischer, R. Nakamura, T. Almeida, J. Brooks
year: 2024
venue: Transactions on Language Systems
doi: 10.1000/tls.2024.0208
keywords: multi-agent, retrieval-augmented generation, coordinator, specialist agents, evidence synthesis
---

# Abstract

Single-call retrieval-augmented generation produces fluent but under-supported
answers on questions that require comparison or synthesis across papers. We decompose
the task into a coordinator and five specialist agents: retrieval, evidence
selection, methodology comparison, research-gap analysis, citation validation and
synthesis. On a 40-question benchmark over scientific abstracts, the multi-agent
system raises citation precision from 0.62 to 0.91 and lowers the unsupported-claim
rate from 0.29 to 0.06, at a latency cost of 2.4 times the single-call baseline.

# 1 Introduction

Retrieval-augmented generation grounds a language model in retrieved text, but
grounding is not the same as attribution: a generator can cite a passage that does
not support its sentence. Splitting the work among agents that each have one job
makes the failure mode observable, because validation becomes a separate, auditable
step rather than an implicit property of a prompt.

# 2 Related Work

Prior multi-agent designs route a question to a domain expert or debate an answer
between two models. Both increase cost without necessarily increasing verifiability.
Our design differs in that every agent returns typed data rather than prose, and the
synthesiser may only emit sentences backed by a validated quotation.

# 3 Methods

The coordinator runs the pipeline and owns the trace. The retrieval agent performs
hybrid retrieval and iterates up to two rounds, mining feedback terms when fewer than
two distinct papers are found or when the best reranked score falls below 0.35. The
evidence agent selects the best-matching sentence from each retrieved chunk and
records its provenance. The methodology agent extracts method, dataset, metric and
reported result for each paper. The gap agent mines limitation and future-work
sentences. The synthesiser writes a lead sentence plus one cited bullet per evidence
item. The citation validator re-reads every source chunk and rejects any quotation it
cannot find, then classifies each answer sentence as supported or unsupported. We
evaluate on a benchmark of 40 questions over 12 papers, with gold document ids and
gold key points.

# 4 Results

Citation precision rises from 0.62 for single-call retrieval-augmented generation to
0.91 for the multi-agent pipeline, and the unsupported-claim rate falls from 0.29 to
0.06. Relevance, measured as coverage of gold key points, improves from 0.54 to 0.71.
Median latency rises from 180 ms to 430 ms on CPU. On gap questions, which ask what
the literature has not solved, the multi-agent system answers 0.78 of questions
correctly compared with 0.21 for the single-call baseline.

# 5 Discussion

The gains come from two places: decomposition, which lets a specialised agent find
limitation sentences that a general retriever ranks poorly, and validation, which
removes citations that a single pass would have kept. Validation is the cheaper of
the two to adopt, and it accounts for roughly half of the citation-precision gain.

# 6 Limitations

The benchmark contains 40 questions, which limits statistical power, and every system
is evaluated with a scripted, extractive synthesiser rather than a large generative
model, so absolute numbers will not transfer. We do not measure cost in tokens, only
in wall-clock latency on one machine. The agents are deterministic and rule-based;
learned agents may trade reliability for fluency. We did not test questions that
require numerical reasoning over tables.

# 7 Future Work

Future work should replace the rule-based synthesiser with a constrained generator
that must copy spans from evidence, and should study whether a learned coordinator
can skip agents adaptively for simple questions.
