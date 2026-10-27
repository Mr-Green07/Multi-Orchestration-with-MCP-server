---
title: Acronym-Aware Query Expansion for Scientific Literature Search
authors: R. Ibrahim, V. Castellan
year: 2020
venue: Proceedings of the Digital Libraries Symposium
doi: 10.1000/dls.2020.0055
keywords: query expansion, acronyms, pseudo-relevance feedback, recall, thesaurus
---

# Abstract

Scientists query literature with acronyms, while papers often spell the expansion
once and then use the abbreviation. We mine acronym to expansion pairs from paper
abstracts and apply them at query time, together with a small hand-built thesaurus and
one round of pseudo-relevance feedback. Recall at ten improves from 0.54 to 0.69 on a
set of 300 acronym-heavy queries.

# 1 Introduction

Query expansion addresses vocabulary mismatch, which is the dominant cause of
retrieval failure in specialised domains. Expansion is risky because added terms can
drift the query away from its intent, so the choice of expansion source matters more
than the number of added terms.

# 2 Related Work

Classic expansion uses a global thesaurus or co-occurrence statistics from the corpus.
Pseudo-relevance feedback expands with terms from the top-ranked documents of an
initial retrieval, which adapts to the corpus but can amplify an early error.

# 3 Methods

We extract acronym and expansion pairs with the pattern where a capitalised phrase is
followed by a parenthesised abbreviation of up to seven characters. Pairs are stored
per corpus and indexed by acronym. At query time, an acronym in the query is expanded
to its most frequent expansion in the corpus, and the expansion is added with lower
weight. A thesaurus of 30 domain pairs covers common paraphrases such as dense and
embedding. Pseudo-relevance feedback adds the six highest-weight terms from the top
three chunks of an initial pass. We evaluate on 300 queries over 500 papers, all of
which contain at least one acronym.

# 4 Results

Recall at ten improves from 0.54 for the unexpanded query to 0.69 with acronym
expansion, thesaurus expansion and one feedback round. Acronym expansion alone
accounts for 0.09 of the improvement, and feedback adds 0.05. Expanding with more than
eight terms degrades precision, and two feedback rounds are worse than one because the
second round reinforces terms from already-retrieved passages.

# 5 Discussion

Expansion is most useful when the expansion source is the corpus itself. A general
thesaurus would introduce terms that never appear in the collection, which adds noise
without adding recall.

# 6 Limitations

Our acronym pattern misses expansions written in lowercase or defined in a footnote,
and it cannot disambiguate acronyms with multiple meanings, such as RAG meaning either
retrieval-augmented generation or red amber green in traffic literature. The evaluation
queries were selected to contain acronyms, so the reported gain overstates the benefit
on a general query distribution. We did not measure the effect on latency.

# 7 Conclusion

Corpus-mined acronym expansion combined with limited feedback is a cheap, effective
recall intervention for scientific search.
