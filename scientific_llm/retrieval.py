"""scientific_llm/retrieval.py
============================
Hybrid retrieval, query expansion, reranking and the retrieval agent
(roadmap items 6-9).

The pipeline, and the reason for each stage:

1. **Query expansion** (:class:`QueryExpander`) - a scientist writes "RAG", the
   paper writes "retrieval-augmented generation"; a thesaurus plus acronym mining
   plus pseudo-relevance feedback closes that gap. Pure recall work.
2. **Hybrid scoring** - BM25 catches exact terminology; the hashing embedding
   catches paraphrase. The two ranked lists are fused with Reciprocal Rank Fusion,
   which needs no score calibration and cannot be dominated by one signal.
3. **Reranking** - a second, query-aware pass over the fused candidates: term
   coverage of the expanded query, phrase adjacency, section prior, and a penalty
   for fragments that start mid-sentence. This is deliberately *not* a trained
   cross-encoder, but it plays the same role (precision) and is inspectable.
4. **Retrieval agent** - runs rounds until the evidence looks sufficient: if the
   best fused score is weak or too few distinct papers are represented, it mines
   terms from the first round and searches again, keeping a stage-by-stage log that
   the trace records.

Every stage records what it did, because the evaluation chapter has to explain
*why* multi-agent retrieval beats a single BM25 pass, not just that it does.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

from scientific_llm.index import CorpusIndex, cosine
from scientific_llm.models import Chunk
from scientific_llm.text import overlap_ratio, stem, terms, tokenize

#: Domain thesaurus: query term -> alternative surface forms.
THESAURUS: dict[str, tuple[str, ...]] = {
    "rag": ("retrieval augmented generation", "retrieval-augmented"),
    "llm": ("large language model", "language model"),
    "llms": ("large language model", "language models"),
    "hallucination": ("fabrication", "unsupported", "faithfulness"),
    "hallucinations": ("fabricated", "unsupported claims"),
    "dense": ("embedding", "bi-encoder", "vector"),
    "sparse": ("bm25", "lexical", "keyword"),
    "bm25": ("sparse", "lexical", "keyword"),
    "rerank": ("reranking", "cross-encoder", "re-rank"),
    "reranking": ("cross-encoder", "re-rank", "second stage"),
    "chunking": ("segmentation", "passage", "splitting"),
    "chunk": ("passage", "segment"),
    "citation": ("attribution", "reference", "grounding"),
    "citations": ("attributions", "references"),
    "gap": ("limitation", "future work", "open problem"),
    "gaps": ("limitations", "open problems"),
    "methodology": ("method", "approach", "experimental setup"),
    "dataset": ("benchmark", "corpus", "collection"),
    "metric": ("evaluation", "measure", "score"),
    "recall": ("retrieval effectiveness", "recall at k"),
    "multi-agent": ("multi agent", "coordinator", "specialist"),
    "agent": ("assistant", "pipeline"),
    "evidence": ("support", "quotation", "grounding"),
    "synthesis": ("summarisation", "aggregation", "summary"),
    "biomedical": ("clinical", "medicine", "health"),
    "scientific": ("scholarly", "academic", "research"),
    "arxiv": ("preprint", "repository"),
    "evaluation": ("benchmark", "assessment"),
}

#: Section labels that deserve a precision bonus when they match the question type.
SECTION_PRIOR: dict[str, float] = {
    "abstract": 1.06, "results": 1.05, "discussion": 1.04, "limitations": 1.04,
    "conclusion": 1.03, "methods": 1.02, "introduction": 1.0, "related work": 0.98,
    "background": 0.98, "future work": 1.02, "references": 0.6, "other": 1.0,
}

#: Question words that signal which sections are likely to hold the answer.
SECTION_HINTS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("limitation", "gap", "open", "future", "unresolved", "challenge"):
        ("limitations", "future work", "discussion", "conclusion"),
    ("method", "approach", "how does", "how do", "technique", "architecture"):
        ("methods", "approach", "experimental setup"),
    ("result", "performance", "score", "improve", "accuracy", "recall"):
        ("results", "evaluation", "findings"),
    ("compare", "comparison", "versus", "vs", "difference", "better"):
        ("results", "methods", "discussion", "related work"),
    ("dataset", "corpus", "benchmark", "data"):
        ("methods", "experimental setup", "results"),
}

ACRONYM_RE = re.compile(r"([A-Z][A-Za-z\-]+(?:\s+[A-Za-z\-]+){0,4})\s*\(([A-Z][A-Z0-9]{1,7})\)")


# --------------------------------------------------------------------------- results
@dataclass
class RetrievalHit:
    """One retrieved chunk with every intermediate score kept for inspection."""

    chunk_id: str
    doc_id: str
    title: str
    year: int | None
    section_label: str
    section_heading: str
    text: str
    score: float
    bm25: float = 0.0
    dense: float = 0.0
    rrf: float = 0.0
    rerank: float = 0.0
    matched_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id, "doc_id": self.doc_id, "title": self.title,
            "year": self.year, "section": self.section_label, "text": self.text,
            "score": round(self.score, 4), "bm25": round(self.bm25, 4),
            "dense": round(self.dense, 4), "rerank": round(self.rerank, 4),
            "matched_terms": self.matched_terms,
        }


@dataclass
class RetrievalResult:
    query: str
    expanded_terms: list[str]
    hits: list[RetrievalHit]
    stages: list[dict[str, object]] = field(default_factory=list)
    rounds: int = 1
    took_ms: float = 0.0

    def doc_ids(self) -> list[str]:
        seen: list[str] = []
        for hit in self.hits:
            if hit.doc_id not in seen:
                seen.append(hit.doc_id)
        return seen

    def top(self, count: int = 5) -> list[RetrievalHit]:
        return self.hits[:count]

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query, "expanded_terms": self.expanded_terms,
            "rounds": self.rounds, "took_ms": round(self.took_ms, 2),
            "stages": self.stages,
            "hits": [hit.as_dict() for hit in self.hits],
        }


# --------------------------------------------------------------------------- expansion
class QueryExpander:
    """Thesaurus + corpus acronyms + optional pseudo-relevance feedback."""

    def __init__(self, index: CorpusIndex, *, use_thesaurus: bool = True,
                 use_acronyms: bool = True) -> None:
        self.index = index
        self.use_thesaurus = use_thesaurus
        self.use_acronyms = use_acronyms
        self._acronyms: dict[str, str] | None = None

    # ------------------------------------------------------------------ corpora
    def acronym_map(self) -> dict[str, str]:
        """Acronym -> expansion, mined from abstracts ("Retrieval-Augmented Generation (RAG)")."""
        if self._acronyms is None:
            mapping: dict[str, str] = {}
            for metadata in self.index.metadata().values():
                blob = " ".join(filter(None, [metadata.title, metadata.abstract]))
                for expansion, acronym in ACRONYM_RE.findall(blob or ""):
                    trimmed = self._trim_expansion(expansion)
                    if trimmed:
                        mapping.setdefault(acronym.lower(), trimmed)
            self._acronyms = mapping
        return self._acronyms

    @staticmethod
    def _trim_expansion(expansion: str) -> str:
        """Keep only the trailing capitalised run of an expansion match.

        ``"Paper We study Retrieval-Augmented Generation"`` becomes
        ``"Retrieval-Augmented Generation"``; a match with no capitalised word is
        discarded rather than stored as a bad synonym.
        """
        words = expansion.split()
        keep: list[str] = []
        for word in reversed(words):
            if word[:1].isupper() or (keep and word[:1].isalpha() and not word.islower()):
                keep.insert(0, word)
            else:
                break
        if len(keep) < 2 and not (keep and "-" in keep[0]):
            return ""
        return " ".join(keep)

    def expand(self, query: str) -> list[str]:
        """Extra terms (not including the query's own tokens)."""
        additions: list[str] = []
        tokens = tokenize(query)
        lowered = " ".join(tokens)
        normalised_query = " ".join(re.split(r"[^a-z0-9]+", lowered)).strip()

        if self.use_thesaurus:
            for token in tokens:
                for synonym in THESAURUS.get(token, ()):
                    if synonym not in lowered:
                        additions.append(synonym)
            for phrase, synonyms in THESAURUS.items():
                if " " in phrase and phrase in lowered:
                    additions.extend(synonyms)

        if self.use_acronyms:
            for acronym, expansion in self.acronym_map().items():
                if acronym in tokens and expansion.lower() not in lowered:
                    additions.append(expansion)
                elif expansion.lower() in lowered and acronym not in tokens:
                    additions.append(acronym)

        seen: set[str] = set()
        unique: list[str] = []
        for addition in additions:
            # Normalise punctuation and case so "Retrieval-Augmented Generation" and
            # "retrieval augmented generation" are recognised as the same synonym.
            key = " ".join(re.split(r"[^a-z0-9]+", addition.lower())).strip()
            if key and key not in seen and key not in normalised_query:
                seen.add(key)
                unique.append(addition)
        return unique

    def feedback_terms(self, chunks: list[Chunk], query: str, limit: int = 6) -> list[str]:
        """Top terms from the best chunks that the query did not already contain."""
        query_terms = set(terms(query))
        counts: dict[str, float] = {}
        for rank, chunk in enumerate(chunks):
            weight = 1.0 / (rank + 1)
            for term in terms(chunk.text):
                if term in query_terms or len(term) < 4:
                    continue
                counts[term] = counts.get(term, 0.0) + weight
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [term for term, _ in ranked[:limit]]


# --------------------------------------------------------------------------- retriever
class HybridRetriever:
    """BM25 + dense hashing embeddings, fused with RRF, then reranked."""

    def __init__(self, index: CorpusIndex, *, k1: float = 1.5, b: float = 0.75,
                 use_expansion: bool = True, mode: str = "hybrid",
                 use_rerank: bool = True) -> None:
        if mode not in {"hybrid", "bm25", "dense"}:
            raise ValueError("mode must be 'hybrid', 'bm25' or 'dense'")
        self.index = index
        self.k1 = k1
        self.b = b
        self.use_expansion = use_expansion
        self.mode = mode
        self.use_rerank = use_rerank
        self.expander = QueryExpander(index)

    # ------------------------------------------------------------------ signals
    def bm25_scores(self, query: str) -> dict[str, float]:
        query_terms = terms(query)
        if not query_terms:
            return {}
        postings = self.index.postings
        lengths = self.index.lengths
        total = len(lengths) or 1
        average = self.index.average_length or 1.0
        scores: dict[str, float] = {}
        for term in query_terms:
            matching = postings.get(term)
            if not matching:
                continue
            idf = math.log(1 + (total - len(matching) + 0.5) / (len(matching) + 0.5))
            for chunk_id, frequency in matching.items():
                length = lengths.get(chunk_id, 0)
                denominator = frequency + self.k1 * (1 - self.b + self.b * length / average)
                scores[chunk_id] = scores.get(chunk_id, 0.0) + idf * (
                    frequency * (self.k1 + 1) / denominator)
        return scores

    def dense_scores(self, query: str) -> dict[str, float]:
        query_vector = self.index.embedder(query)
        return {chunk_id: cosine(query_vector, vector)
                for chunk_id, vector in self.index.vectors.items()}

    @staticmethod
    def _rrf(ranked: list[tuple[str, float]], weight: float, k: int = 60) -> dict[str, float]:
        return {chunk_id: weight * (1.0 / (k + rank + 1))
                for rank, (chunk_id, _) in enumerate(ranked)}

    def search(self, query: str, *, k: int = 8, pool: int = 40,
               expansions: list[str] | None = None) -> RetrievalResult:
        started = time.perf_counter()
        expansions = expansions if expansions is not None else (
            self.expander.expand(query) if self.use_expansion else [])
        expanded_query = " ".join([query, *expansions]).strip()

        stages: list[dict[str, object]] = []
        bm25 = self.bm25_scores(expanded_query)
        dense = self.dense_scores(expanded_query)
        stages.append({"stage": "lexical", "scored": len(bm25)})
        stages.append({"stage": "dense", "scored": len(dense)})

        lexical_rank = sorted(bm25.items(), key=lambda item: (-item[1], item[0]))[:pool]
        dense_rank = sorted(dense.items(), key=lambda item: (-item[1], item[0]))[:pool]
        if self.mode == "bm25":
            fused = self._rrf(lexical_rank, 1.0)
            weights = {"lexical": 1.0}
        elif self.mode == "dense":
            fused = self._rrf(dense_rank, 1.0)
            weights = {"dense": 1.0}
        else:
            fused = self._merge(self._rrf(lexical_rank, 1.0), self._rrf(dense_rank, 0.8))
            weights = {"lexical": 1.0, "dense": 0.8}
        stages.append({"stage": "fusion", "candidates": len(fused),
                       "method": "rrf" if len(weights) > 1 else self.mode,
                       "weights": weights})

        candidates = sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:pool]
        if self.use_rerank:
            hits = self.rerank(query, expanded_query, candidates, bm25, dense)
            stages.append({"stage": "rerank", "candidates": len(candidates)})
        else:
            hits = self._plain_hits(query, candidates, bm25, dense)
            stages.append({"stage": "no-rerank", "candidates": len(candidates)})

        trimmed = self._diversify(hits, k=k, max_per_doc=3)
        stages.append({"stage": "select", "returned": len(trimmed)})
        return RetrievalResult(
            query=query, expanded_terms=expansions, hits=trimmed, stages=stages,
            took_ms=(time.perf_counter() - started) * 1000.0)

    @staticmethod
    def _merge(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
        merged = dict(left)
        for key, value in right.items():
            merged[key] = merged.get(key, 0.0) + value
        return merged

    def rerank(self, query: str, expanded_query: str,
               candidates: list[tuple[str, float]],
               bm25: dict[str, float], dense: dict[str, float]) -> list[RetrievalHit]:
        if not candidates:
            return []
        query_terms = set(terms(expanded_query))
        raw_query_terms = set(terms(query))
        best = max(score for _, score in candidates) or 1.0
        section_targets = self._section_targets(query)

        hits: list[RetrievalHit] = []
        metadata = self.index.metadata()
        for chunk_id, fused_score in candidates:
            chunk = self.index.chunk(chunk_id)
            if chunk is None:
                continue
            chunk_terms = set(terms(chunk.text))
            coverage = overlap_ratio(query_terms, chunk_terms)
            exact_overlap = len(query_terms & chunk_terms)
            phrase = self._phrase_bonus(query, chunk.text)
            prior = SECTION_PRIOR.get(chunk.section_label, 1.0)
            hint = 1.08 if chunk.section_label in section_targets else 1.0
            fragment_penalty = 0.94 if chunk.starts_mid_sentence else 1.0
            short_penalty = 0.95 if chunk.token_count < 30 else 1.0

            rerank = (
                0.45 * (fused_score / best)
                + 0.25 * coverage
                + 0.10 * phrase
                + 0.10 * min(exact_overlap, 6) / 6
                + 0.10 * (prior - 1.0) * 4
            ) * hint * fragment_penalty * short_penalty

            meta = metadata.get(chunk.doc_id)
            hits.append(RetrievalHit(
                chunk_id=chunk_id, doc_id=chunk.doc_id,
                title=meta.title if meta else chunk.doc_id,
                year=meta.year if meta else None,
                section_label=chunk.section_label,
                section_heading=chunk.section_heading, text=chunk.text,
                score=rerank, bm25=bm25.get(chunk_id, 0.0),
                dense=dense.get(chunk_id, 0.0), rrf=fused_score, rerank=rerank,
                matched_terms=sorted(query_terms & chunk_terms),
            ))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        _ = raw_query_terms
        return hits

    @staticmethod
    def _section_targets(query: str) -> set[str]:
        lowered = " ".join(tokenize(query))
        targets: set[str] = set()
        for cues, sections in SECTION_HINTS.items():
            if any(cue in lowered for cue in cues):
                targets.update(sections)
        return targets

    @staticmethod
    def _phrase_bonus(query: str, text: str) -> float:
        """Reward adjacent query bigrams appearing verbatim in the chunk."""
        query_tokens = tokenize(query)
        if len(query_tokens) < 2:
            return 0.0
        lowered = " ".join(tokenize(text))
        bigrams = {f"{left} {right}" for left, right in
                   zip(query_tokens, query_tokens[1:], strict=False)}
        if not bigrams:
            return 0.0
        found = sum(1 for bigram in bigrams if bigram in lowered)
        return found / len(bigrams)

    def _plain_hits(self, query: str, candidates: list[tuple[str, float]],
                    bm25: dict[str, float],
                    dense: dict[str, float]) -> list[RetrievalHit]:
        """Fusion order only - the first-stage ranking, no second-stage scoring."""
        query_terms = set(terms(query))
        metadata = self.index.metadata()
        hits: list[RetrievalHit] = []
        for chunk_id, fused_score in candidates:
            chunk = self.index.chunk(chunk_id)
            if chunk is None:
                continue
            meta = metadata.get(chunk.doc_id)
            chunk_terms = set(terms(chunk.text))
            hits.append(RetrievalHit(
                chunk_id=chunk_id, doc_id=chunk.doc_id,
                title=meta.title if meta else chunk.doc_id,
                year=meta.year if meta else None,
                section_label=chunk.section_label,
                section_heading=chunk.section_heading, text=chunk.text,
                score=fused_score, bm25=bm25.get(chunk_id, 0.0),
                dense=dense.get(chunk_id, 0.0), rrf=fused_score, rerank=0.0,
                matched_terms=sorted(query_terms & chunk_terms)))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        return hits

    @staticmethod
    def _diversify(hits: list[RetrievalHit], *, k: int,
                   max_per_doc: int) -> list[RetrievalHit]:
        selected: list[RetrievalHit] = []
        per_doc: dict[str, int] = {}
        for hit in hits:
            if per_doc.get(hit.doc_id, 0) >= max_per_doc:
                continue
            selected.append(hit)
            per_doc[hit.doc_id] = per_doc.get(hit.doc_id, 0) + 1
            if len(selected) >= k:
                break
        return selected


# --------------------------------------------------------------------------- agent
class RetrievalAgent:
    """Iterative retriever: expand, search, judge, and search again if needed.

    The stopping rule is explicit so the behaviour is arguable and testable:

    * stop when there are at least ``min_docs`` distinct papers and the best rerank
      score clears ``score_floor``;
    * otherwise mine feedback terms from what was found and run one more round, up
      to ``max_rounds``;
    * never return the same chunk twice.
    """

    def __init__(self, retriever: HybridRetriever, *, max_rounds: int = 2,
                 min_docs: int = 2, score_floor: float = 0.35) -> None:
        self.retriever = retriever
        self.max_rounds = max_rounds
        self.min_docs = min_docs
        self.score_floor = score_floor

    def retrieve(self, question: str, *, k: int = 8) -> RetrievalResult:
        started = time.perf_counter()
        expansions = self.retriever.expander.expand(question)
        collected: dict[str, RetrievalHit] = {}
        stages: list[dict[str, object]] = []
        rounds = 0

        while rounds < self.max_rounds:
            rounds += 1
            result = self.retriever.search(question, k=k, expansions=expansions)
            for hit in result.hits:
                existing = collected.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    collected[hit.chunk_id] = hit

            stages.extend([{**stage, "round": rounds} for stage in result.stages])
            distinct_docs = len({hit.doc_id for hit in collected.values()})
            best = max((hit.score for hit in collected.values()), default=0.0)
            sufficient = distinct_docs >= self.min_docs and best >= self.score_floor
            stages.append({"stage": "judge", "round": rounds,
                           "distinct_docs": distinct_docs, "best_score": round(best, 4),
                           "sufficient": sufficient})
            if sufficient or rounds >= self.max_rounds:
                break

            top_chunks = [self.retriever.index.chunk(hit.chunk_id)
                          for hit in sorted(collected.values(), key=lambda h: -h.score)[:3]]
            feedback = self.retriever.expander.feedback_terms(
                [chunk for chunk in top_chunks if chunk], question)
            new_terms = [term for term in feedback if term not in expansions]
            stages.append({"stage": "feedback", "round": rounds, "terms": new_terms})
            if not new_terms:
                break
            expansions = [*expansions, *new_terms]

        ordered = sorted(collected.values(), key=lambda hit: (-hit.score, hit.chunk_id))
        diversified = HybridRetriever._diversify(ordered, k=k, max_per_doc=3)
        return RetrievalResult(
            query=question, expanded_terms=expansions, hits=diversified,
            stages=stages, rounds=rounds,
            took_ms=(time.perf_counter() - started) * 1000.0)


def stem_query(query: str) -> str:
    """Exposed for evaluation scripts that want the exact analyser used at index time."""
    return " ".join(stem(term) for term in tokenize(query))
