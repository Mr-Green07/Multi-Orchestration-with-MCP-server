"""scientific_llm/baselines.py
============================
The two systems the multi-agent pipeline is measured against (roadmap items 18-19).

Both return the *same* :class:`AnswerBundle` shape as the coordinator, because an
evaluation that compares systems returning different objects ends up comparing the
plumbing instead of the behaviour.

* :class:`ConventionalRAGSystem` - the textbook recipe, one pass: embed the question,
  take the top-k chunks, concatenate them, and summarise with citations. No query
  expansion, no fusion, no reranking, no validator, no gap analysis, no comparison.
* :class:`SingleAgentSystem` - a stronger one-agent baseline: the full hybrid
  pipeline (expansion, fusion, reranking) in a single round, then a cited summary.
  It is what a careful practitioner would ship without decomposition.

Neither baseline is a straw man: both use the same index, the same embedder and the
same sentence extractor as the multi-agent system. The only difference is the
*process*, which is exactly what the comparison is meant to isolate.
"""
from __future__ import annotations

import time

from scientific_llm.agents import EvidenceAgent, EvidenceSynthesisAgent, best_sentence
from scientific_llm.models import AnswerBundle, Evidence
from scientific_llm.retrieval import HybridRetriever, RetrievalAgent
from scientific_llm.tracing import Trace


class ConventionalRAGSystem:
    """Single-pass dense retrieval, concatenated context, cited summary."""

    name = "conventional_rag"

    def __init__(self, index, *, k: int = 8, context_chunks: int = 6) -> None:
        self.index = index
        self.k = k
        self.context_chunks = context_chunks
        # Deliberately the plain recipe: dense-only, no expansion, no rerank.
        self.retriever = HybridRetriever(index, use_expansion=False, mode="dense",
                                         use_rerank=False)
        self.synthesiser = EvidenceSynthesisAgent()

    def answer(self, question: str) -> AnswerBundle:
        started = time.perf_counter()
        trace = Trace(question, system=self.name)
        with trace.span("rag", "retrieve") as span:
            result = self.retriever.search(question, k=self.k)
            span.note(f"{len(result.hits)} chunks (dense only, no expansion)",
                      stages=result.stages)

        with trace.span("rag", "generate") as span:
            context = "\n\n".join(hit.text for hit in result.hits[: self.context_chunks])
            evidence: list[Evidence] = []
            seen: set[str] = set()
            for hit in result.hits[: self.context_chunks]:
                quote = best_sentence(hit.text, question)
                if not quote or quote.lower()[:80] in seen:
                    continue
                seen.add(quote.lower()[:80])
                evidence.append(Evidence(
                    evidence_id=f"E{len(evidence) + 1}", claim=quote, quote=quote,
                    doc_id=hit.doc_id, chunk_id=hit.chunk_id, title=hit.title,
                    year=hit.year, section=hit.section_label, score=round(hit.score, 4),
                    verified=True, verification_note="rag: accepted without re-check",
                ))
            answer = self.synthesiser.synthesize(question, evidence)
            span.note(f"{len(evidence)} citations, {len(context)} context characters")

        return AnswerBundle(
            question=question, answer=answer, evidence=evidence,
            retrieved_doc_ids=result.doc_ids(), system=self.name,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            trace=trace.as_dict(),
            notes=["single dense retrieval pass; citations accepted without re-check"],
        )


class SingleAgentSystem:
    """One agent, one pass: hybrid retrieval plus a short cited summary."""

    name = "single_agent"

    def __init__(self, index, *, k: int = 8) -> None:
        self.index = index
        self.k = k
        self.retriever = RetrievalAgent(HybridRetriever(index), max_rounds=1)
        self.evidence_agent = EvidenceAgent()
        self.synthesiser = EvidenceSynthesisAgent()

    def answer(self, question: str) -> AnswerBundle:
        started = time.perf_counter()
        trace = Trace(question, system=self.name)
        with trace.span("single_agent", "retrieve") as span:
            result = self.retriever.retrieve(question, k=self.k)
            span.note(f"{len(result.hits)} chunks, 1 round", stages=result.stages)

        with trace.span("single_agent", "answer") as span:
            evidence = self.evidence_agent.build(question, result, limit=6)
            for item in evidence:                     # accepted, not re-verified
                item.verified = True
                item.verification_note = "single agent: accepted without re-check"
            answer = self.synthesiser.synthesize(question, evidence)
            span.note(f"{len(evidence)} citations", words=len(answer.split()))

        return AnswerBundle(
            question=question, answer=answer, evidence=evidence,
            retrieved_doc_ids=result.doc_ids(), system=self.name,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            trace=trace.as_dict(),
            notes=["one agent, one pass: no gap analysis, no comparison, no validator"],
        )


SYSTEMS = {
    ConventionalRAGSystem.name: ConventionalRAGSystem,
    SingleAgentSystem.name: SingleAgentSystem,
}
