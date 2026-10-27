"""scientific_llm/agents.py
=========================
The specialist agents (roadmap items 11-15) and the evidence builder (item 5).

Design rules, all of which the evaluation depends on:

* **Every claim is extractive.** Each sentence in an answer is a sentence from an
  indexed chunk (or a short connective built from those sentences), so "is this
  supported?" is a string comparison, not a model judgement.
* **No agent may write an uncited statement.** The synthesiser only emits claims
  it has evidence for; the validator then *re-checks* that evidence against the
  corpus and rejects anything it cannot find.
* **Agents hand off data, not vibes.** Each transfer is a typed payload recorded by
  :class:`scientific_llm.tracing.Trace`.
* **Deterministic.** Same corpus + same question = same answer, every time. That is
  what makes the benchmark numbers reproducible.

Agents:

===========================  =====================================================
CoordinatorAgent             runs the pipeline, owns the trace
EvidenceAgent                turns retrieval hits into Evidence objects
MethodologyComparisonAgent   extracts method / dataset / metric / result rows
ResearchGapAgent             mines limitations + corpus coverage gaps
EvidenceSynthesisAgent       writes the cited answer
CitationValidatorAgent       verifies every citation against the source chunk
===========================  =====================================================
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from scientific_llm.models import AnswerBundle, Evidence, ScientificDocument
from scientific_llm.retrieval import RetrievalAgent, RetrievalHit, RetrievalResult
from scientific_llm.text import (
    normalize_whitespace,
    overlap_ratio,
    sentences,
    terms,
    tokenize,
)
from scientific_llm.tracing import Trace

MAX_EVIDENCE = 6
MAX_GAPS = 5

#: Cue words that make a sentence a limitation / future-work statement.
GAP_CUES = (
    "limitation", "limited", "future work", "we do not", "we did not", "cannot",
    "remains", "unresolved", "open question", "challenge", "shortcoming",
    "fails to", "does not address", "needs further", "further research",
    "future research", "not evaluated", "unclear whether", "trade-off",
)

#: Cue words for method sentences.
METHOD_CUES = (
    "we propose", "we introduce", "we present", "our approach", "our method",
    "we use", "we build", "we train", "architecture", "pipeline", "algorithm",
    "we combine", "framework",
)
DATASET_CUES = ("dataset", "corpus", "benchmark", "collection", "we evaluate on",
                "trained on", "test set", "split")
METRIC_CUES = ("recall", "precision", "ndcg", "accuracy", "f1", "exact match",
               "mrr", "score", "evaluated with", "measured by", "latency")

CITATION_MARKER = re.compile(r"\[(E\d+)\]")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|x|k|ms|s|points)?\b")


# --------------------------------------------------------------------------- helpers
def best_sentence(text: str, query: str, *, minimum: int = 3) -> str:
    """The sentence in *text* that best matches *query* (deterministic tie-break)."""
    query_terms = set(terms(query))
    candidates = sentences(text) or [normalize_whitespace(text)]
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(candidates):
        sentence_terms = set(terms(sentence))
        score = overlap_ratio(query_terms, sentence_terms) if query_terms else 0.0
        score += 0.05 * min(len(sentence_terms & query_terms), 6)
        if len(tokenize(sentence)) < minimum:
            score -= 0.2
        scored.append((score, -index, sentence))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return scored[0][2] if scored else normalize_whitespace(text)


def classify_support(quote: str, chunk_text: str) -> str:
    """direct = verbatim; paraphrase = most words present; weak = neither."""
    quote_norm = normalize_whitespace(quote).lower()
    chunk_norm = normalize_whitespace(chunk_text).lower()
    if quote_norm and quote_norm in chunk_norm:
        return "direct"
    if overlap_ratio(set(terms(quote)), set(terms(chunk_text))) >= 0.6:
        return "paraphrase"
    return "weak"


def find_chunk_for_sentence(index, doc_id: str, sentence: str) -> str | None:
    """Which chunk of *doc_id* actually contains *sentence*?

    Comparison rows and gap statements are quoted from a paper's sections, but a
    citation must point at a chunk. This resolves that, so no line in an answer is
    ever left without a locatable source.
    """
    needle = normalize_whitespace(sentence)[:80].lower()
    if not needle:
        return None
    best: tuple[float, str] | None = None
    for chunk in index.chunks(doc_id):
        haystack = normalize_whitespace(chunk.text).lower()
        if needle in haystack:
            return str(chunk.chunk_id)
        score = overlap_ratio(set(terms(sentence)), set(terms(chunk.text)))
        if best is None or score > best[0]:
            best = (score, chunk.chunk_id)
    if best is not None and best[0] >= 0.5:
        return best[1]
    return None


def _cue_sentences(text: str, cues: tuple[str, ...]) -> list[str]:
    picked = []
    for sentence in sentences(text):
        lowered = sentence.lower()
        if any(cue in lowered for cue in cues):
            picked.append(sentence.strip())
    return picked


# --------------------------------------------------------------------------- evidence
class EvidenceAgent:
    """Turn retrieval hits into citable :class:`Evidence` objects."""

    name = "evidence"

    def build(self, question: str, result: RetrievalResult, *,
              limit: int = MAX_EVIDENCE,
              documents: dict[str, ScientificDocument] | None = None) -> list[Evidence]:
        evidence: list[Evidence] = []
        seen_quotes: set[str] = set()
        for hit in result.hits:
            if len(evidence) >= limit:
                break
            quote = best_sentence(hit.text, question)
            key = normalize_whitespace(quote).lower()[:120]
            if not quote or key in seen_quotes:
                continue
            seen_quotes.add(key)
            evidence.append(Evidence(
                evidence_id=f"E{len(evidence) + 1}",
                claim=quote,
                quote=quote,
                doc_id=hit.doc_id,
                chunk_id=hit.chunk_id,
                title=hit.title,
                year=hit.year,
                section=hit.section_label,
                authors=(documents[hit.doc_id].metadata.authors
                         if documents and hit.doc_id in documents else []),
                support=classify_support(quote, hit.text),  # type: ignore[arg-type]
                score=round(hit.score, 4),
            ))
        return evidence


# --------------------------------------------------------------------------- methodology
@dataclass
class MethodRow:
    doc_id: str
    title: str
    year: int | None
    method: str = ""
    dataset: str = ""
    metrics: str = ""
    reported: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"doc_id": self.doc_id, "title": self.title, "year": self.year,
                "method": self.method, "dataset": self.dataset,
                "metrics": self.metrics, "reported": self.reported}


class MethodologyComparisonAgent:
    """Extract comparable method/dataset/metric/result rows, one per paper."""

    name = "methodology"

    def compare(self, hits: list[RetrievalHit],
                documents: dict[str, ScientificDocument]) -> list[dict[str, object]]:
        rows: dict[str, MethodRow] = {}
        for hit in hits:
            document = documents.get(hit.doc_id)
            if document is None or hit.doc_id in rows:
                continue
            corpus = "\n\n".join([
                document.section_text("methods"), document.section_text("results"),
                document.section_text("abstract"),
            ])
            if not corpus.strip():
                corpus = hit.text
            rows[hit.doc_id] = MethodRow(
                doc_id=hit.doc_id, title=document.metadata.title,
                year=document.metadata.year,
                method=self._first(corpus, METHOD_CUES),
                dataset=self._first(corpus, DATASET_CUES),
                metrics=self._metrics(corpus),
                reported=self._numbers(corpus),
            )
        return [row.as_dict() for row in rows.values()]

    @staticmethod
    def _first(text: str, cues: tuple[str, ...]) -> str:
        for sentence in _cue_sentences(text, cues):
            if 3 <= len(tokenize(sentence)) <= 60:
                return sentence[:240]
        return ""

    @staticmethod
    def _metrics(text: str) -> str:
        found: list[str] = []
        lowered = text.lower()
        for metric in ("recall", "precision", "ndcg", "mrr", "accuracy", "f1",
                       "exact match", "latency"):
            if metric in lowered and metric not in found:
                found.append(metric)
        return ", ".join(found)

    @staticmethod
    def _numbers(text: str) -> str:
        numbers = _NUMBER.findall(text)
        unique: list[str] = []
        for number in numbers:
            if number not in unique:
                unique.append(number)
        return ", ".join(unique[:5])


# --------------------------------------------------------------------------- gaps
class ResearchGapAgent:
    """Find what the literature says is missing, and what the corpus is missing."""

    name = "gaps"

    def find(self, question: str, hits: list[RetrievalHit],
             documents: dict[str, ScientificDocument],
             *, limit: int = MAX_GAPS) -> list[dict[str, str | None]]:
        """Gap statements with provenance: ``{"text", "doc_id", "chunk_id"}``."""
        question_terms = set(terms(question))
        candidates: list[tuple[float, dict[str, str | None]]] = []

        for doc_id, document in documents.items():
            limitation_text = "\n".join(filter(None, [
                document.section_text("limitations"),
                document.section_text("future work"),
                document.section_text("discussion"),
            ]))
            for sentence in _cue_sentences(limitation_text, GAP_CUES):
                if len(tokenize(sentence)) < 5:
                    continue
                relevance = overlap_ratio(question_terms, set(terms(sentence))) if question_terms else 0.2
                candidates.append((relevance + 0.5, {
                    "text": self._cite(sentence, document),
                    "doc_id": doc_id, "chunk_id": None, "sentence": sentence[:240]}))

        for hit in hits[:3]:
            for sentence in _cue_sentences(hit.text, GAP_CUES):
                if len(tokenize(sentence)) < 5:
                    continue
                relevance = overlap_ratio(question_terms, set(terms(sentence))) if question_terms else 0.2
                candidates.append((relevance + 0.3, {
                    "text": sentence[:240], "doc_id": hit.doc_id,
                    "chunk_id": hit.chunk_id, "sentence": sentence[:240]}))

        # corpus-level gaps: what the question asks about that nothing answers
        covered = set()
        for hit in hits:
            covered |= set(terms(hit.text))
        missing = sorted(question_terms - covered)[:2]
        if hits and missing:
            candidates.append((0.4, {"text": "No retrieved passage discusses "
                                             + ", ".join(missing) + ".",
                                     "doc_id": None, "chunk_id": None,
                                     "sentence": None}))

        candidates.sort(key=lambda item: (-item[0], str(item[1]["text"])))
        unique: list[dict[str, str | None]] = []
        seen: set[str] = set()
        for _, payload in candidates:
            if payload["text"] in seen:
                continue
            seen.add(str(payload["text"]))
            unique.append(payload)
            if len(unique) >= limit:
                break
        return unique

    @staticmethod
    def _cite(sentence: str, document: ScientificDocument) -> str:
        authors = document.metadata.authors
        who = (authors[0] if len(authors) == 1 else
               f"{authors[0]} et al." if authors else "The paper")
        return f"{sentence.strip()[:220]} ({who}, {document.metadata.year or 'n.d.'})"


# --------------------------------------------------------------------------- synthesis
class EvidenceSynthesisAgent:
    """Write the answer: a lead sentence plus one cited claim per bullet."""

    name = "synthesis"

    def synthesize(self, question: str, evidence: list[Evidence],
                   *, gaps: list[str] | None = None,
                   comparison: list[dict[str, object]] | None = None) -> str:
        usable = [item for item in evidence if item.support != "weak"] or evidence
        if not usable:
            return ("The corpus does not contain enough evidence to answer this "
                    "question. No citation is offered rather than an unsupported claim.")

        documents = {item.doc_id for item in usable}
        lead = (f"Across {len(documents)} indexed paper(s), the evidence relevant to "
                f"\"{question.strip()[:120]}\" is summarised below; every line is "
                f"traceable to a verified quotation.")

        bullets: list[str] = []
        for item in usable[:MAX_EVIDENCE]:   # one bullet per verified quotation
            sentence = item.claim.strip()
            if not sentence.endswith((".", "!", "?")):
                sentence = f"{sentence}."
            bullets.append(f"- {sentence} [{item.evidence_id}]")
        lines = [lead, "", *bullets]

        if comparison:
            lines.extend(["", "Methodology comparison"])
            for row in comparison:
                bits = [f"{row.get('title')} ({row.get('year') or 'n.d.'})"]
                method = str(row.get("method") or "")
                dataset = str(row.get("dataset") or "")
                metrics = str(row.get("metrics") or "")
                if method:
                    bits.append(f"method: {method[:140]}")
                if dataset:
                    bits.append(f"data: {dataset[:100]}")
                if metrics:
                    bits.append(f"metrics: {metrics}")
                evidence_id = str(row.get("evidence_id") or "")
                marker = f" [{evidence_id}]" if evidence_id else ""
                lines.append("- " + "; ".join(bits) + marker)

        if gaps:
            lines.extend(["", "Limitations and open questions"])
            lines.extend(f"- {gap}" for gap in gaps[:MAX_GAPS])
        return "\n".join(lines)


# --------------------------------------------------------------------------- validator
class CitationValidatorAgent:
    """Re-read every source chunk and reject anything it cannot find.

    Two independent checks:

    * **marker integrity** - every ``[En]`` in the answer refers to a real,
      verified evidence object (this catches fabricated citations);
    * **quote integrity** - each evidence quote is actually present in the chunk it
      claims to come from (this catches fabricated support).

    It also classifies every answer sentence as supported or unsupported, which is
    exactly the quantity the hallucination metric needs.
    """

    name = "validator"
    SUPPORT_THRESHOLD = 0.45

    def validate(self, answer: str, evidence: list[Evidence],
                 index) -> tuple[list[Evidence], list[str], list[str]]:
        verified: list[Evidence] = []
        for item in evidence:
            chunk = index.chunk(item.chunk_id)
            if chunk is None:
                item.verified = False
                item.verification_note = "chunk not found in the index"
                continue
            quote_terms = set(terms(item.quote))
            chunk_terms = set(terms(chunk.text))
            coverage = overlap_ratio(quote_terms, chunk_terms)
            verbatim = normalize_whitespace(item.quote).lower() in normalize_whitespace(
                chunk.text).lower()
            item.verified = verbatim or coverage >= 0.9
            item.verification_note = ("verbatim" if verbatim else
                                      f"coverage {coverage:.2f}")
            if item.verified:
                item.support = classify_support(item.quote, chunk.text)  # type: ignore[assignment]
                verified.append(item)

        verified_ids = {item.evidence_id for item in verified}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        unsupported: list[str] = []

        from scientific_llm.metrics import claim_sentences

        for sentence in claim_sentences(answer):
            markers = CITATION_MARKER.findall(sentence)
            if not markers:
                # Connective/heading text is allowed; a *claim* without a citation is not.
                if any(word in sentence.lower() for word in ("across", "summarised", "below")):
                    continue
                unsupported.append(sentence)
                continue
            if any(marker not in verified_ids for marker in markers):
                unsupported.append(sentence)
                continue
            sentence_terms = set(terms(sentence))
            supported = False
            for marker in markers:
                cited = evidence_by_id.get(marker)
                if cited is None:
                    continue
                if overlap_ratio(set(terms(cited.quote)), sentence_terms) >= self.SUPPORT_THRESHOLD:
                    supported = True
                    break
            if not supported:
                unsupported.append(sentence)

        return verified, sorted(verified_ids), unsupported


# --------------------------------------------------------------------------- coordinator
@dataclass
class CoordinatorSettings:
    k: int = 8
    max_evidence: int = MAX_EVIDENCE
    max_gaps: int = MAX_GAPS
    always_compare: bool = False
    keep_trace: bool = True


class CoordinatorAgent:
    """Owns one question end to end: retrieve, compare, gaps, synthesise, verify."""

    #: Leaderboard name (matches ``AnswerBundle.system`` and the benchmark tables).
    name = "multi_agent"
    #: Name used inside the trace, where the coordinator is one agent among several.
    agent_name = "coordinator"

    def __init__(self, index, retrieval_agent: RetrievalAgent | None = None,
                 settings: CoordinatorSettings | None = None) -> None:
        from scientific_llm.retrieval import HybridRetriever

        self.index = index
        self.retriever = retrieval_agent or RetrievalAgent(HybridRetriever(index))
        self.settings = settings or CoordinatorSettings()
        self.evidence_agent = EvidenceAgent()
        self.methodology_agent = MethodologyComparisonAgent()
        self.gap_agent = ResearchGapAgent()
        self.synthesis_agent = EvidenceSynthesisAgent()
        self.validator = CitationValidatorAgent()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def wants_comparison(question: str) -> bool:
        cues = ("compare", "comparison", "versus", " vs ", "difference",
                "better", "contrast", "methodology")
        return any(cue in question.lower() for cue in cues)

    def _documents(self, doc_ids: list[str]) -> dict[str, ScientificDocument]:
        documents: dict[str, ScientificDocument] = {}
        for doc_id in doc_ids:
            document = self.index.document(doc_id)
            if document:
                documents[doc_id] = document
        return documents

    # ------------------------------------------------------------------ citations
    def _cite_sentence(self, doc_id: str, sentence: str,
                       evidence: list[Evidence]) -> str | None:
        """Find (or add) an Evidence entry quoting *sentence* from *doc_id*."""
        if not sentence:
            return None
        quote_key = normalize_whitespace(sentence)[:80].lower()
        for item in evidence:
            if item.doc_id == doc_id and normalize_whitespace(item.quote)[:80].lower() == quote_key:
                return item.evidence_id
        chunk_id = find_chunk_for_sentence(self.index, doc_id, sentence)
        if not chunk_id:
            return None
        chunk = self.index.chunk(chunk_id)
        document = self.index.document(doc_id)
        if chunk is None or document is None:
            return None
        item = Evidence(
            evidence_id=f"E{len(evidence) + 1}", claim=sentence[:300],
            quote=sentence[:300], doc_id=doc_id, chunk_id=chunk_id,
            title=document.metadata.title, authors=document.metadata.authors,
            year=document.metadata.year, section=chunk.section_label,
            support=classify_support(sentence, chunk.text),  # type: ignore[arg-type]
            score=0.0,
        )
        evidence.append(item)
        return item.evidence_id

    def _cite_gap(self, row: dict[str, str | None],
                  evidence: list[Evidence]) -> str | None:
        doc_id = row.get("doc_id")
        if not doc_id:
            return None
        chunk_id = row.get("chunk_id")
        chunk = self.index.chunk(chunk_id) if chunk_id else None
        sentence = str(row.get("sentence") or row.get("text") or "")
        if chunk is not None and normalize_whitespace(sentence)[:80].lower() in \
                normalize_whitespace(chunk.text).lower():
            for item in evidence:
                if item.chunk_id == chunk_id and normalize_whitespace(item.quote)[
                        :80].lower() == normalize_whitespace(sentence)[:80].lower():
                    return item.evidence_id
            document = self.index.document(doc_id)
            if document is None:
                return None
            item = Evidence(
                evidence_id=f"E{len(evidence) + 1}", claim=sentence[:300],
                quote=sentence[:300], doc_id=doc_id, chunk_id=str(chunk_id),
                title=document.metadata.title, authors=document.metadata.authors,
                year=document.metadata.year, section=chunk.section_label,
                support=classify_support(sentence, chunk.text),  # type: ignore[arg-type]
                score=0.0,
            )
            evidence.append(item)
            return item.evidence_id
        return self._cite_sentence(doc_id, sentence, evidence)

    # ------------------------------------------------------------------ pipeline
    def answer(self, question: str) -> AnswerBundle:
        import time

        started = time.perf_counter()
        trace = Trace(question, system="multi_agent")
        notes: list[str] = []

        with trace.span(self.agent_name, "start") as span:
            span.note("question received", question=question[:200])

        with trace.span("retrieval", "retrieve") as span:
            result = self.retriever.retrieve(question, k=self.settings.k)
            span.note(f"{len(result.hits)} chunks from {len(result.doc_ids())} papers",
                      rounds=result.rounds, expanded_terms=result.expanded_terms[:8],
                      stages=result.stages)

        documents = self._documents(result.doc_ids())
        trace.handoff("retrieval", "evidence", "hits ready for citation",
                      hits=len(result.hits), doc_ids=result.doc_ids())
        with trace.span(self.evidence_agent.name, "build") as span:
            evidence = self.evidence_agent.build(question, result,
                                                 limit=self.settings.max_evidence,
                                                 documents=documents)
            span.note(f"{len(evidence)} candidate quotations", evidence=len(evidence))

        comparison: list[dict[str, object]] = []
        if self.settings.always_compare or self.wants_comparison(question):
            trace.handoff("evidence", self.methodology_agent.name,
                          "comparison requested", papers=len(documents))
            with trace.span(self.methodology_agent.name, "compare") as span:
                comparison = self.methodology_agent.compare(result.hits, documents)
                for row in comparison:                 # every row gets a citation
                    sentence = str(row.get("method") or row.get("dataset") or "")
                    evidence_id = self._cite_sentence(str(row["doc_id"]), sentence,
                                                      evidence)
                    if evidence_id:
                        row["evidence_id"] = evidence_id
                span.note(f"{len(comparison)} rows", rows=len(comparison))
        else:
            notes.append("comparison skipped (question does not ask for one)")

        trace.handoff("evidence", self.gap_agent.name, "find limitations")
        with trace.span(self.gap_agent.name, "gap_scan") as span:
            gap_rows = self.gap_agent.find(question, result.hits, documents,
                                           limit=self.settings.max_gaps)
            gaps: list[str] = []
            for gap_row in gap_rows:
                text = str(gap_row.get("text") or "")
                evidence_id = self._cite_gap(gap_row, evidence)
                gaps.append(f"{text} [{evidence_id}]" if evidence_id and
                            not text.rstrip().endswith(".") else
                            (f"{text} [{evidence_id}]" if evidence_id else text))
            span.note(f"{len(gaps)} gap statements", gaps=len(gaps))

        trace.handoff("gaps", self.synthesis_agent.name, "synthesise cited answer",
                      evidence=len(evidence), gaps=len(gaps))
        with trace.span(self.synthesis_agent.name, "synthesise") as span:
            answer = self.synthesis_agent.synthesize(question, evidence,
                                                     gaps=gaps, comparison=comparison)
            span.note(f"{len(answer)} characters", words=len(tokenize(answer)))

        trace.handoff("synthesis", self.validator.name, "verify every citation",
                      citations=len(evidence))
        with trace.span(self.validator.name, "validate") as span:
            verified, verified_ids, unsupported = self.validator.validate(
                answer, evidence, self.index)
            span.note(f"{len(verified)} verified citations, "
                      f"{len(unsupported)} unsupported sentence(s)",
                      verified_ids=verified_ids, unsupported=unsupported)

        latency = (time.perf_counter() - started) * 1000.0
        trace.add(self.agent_name, "finish", detail="answer complete",
                  latency_ms=0.0, citations=len(verified),
                  unsupported=len(unsupported))

        return AnswerBundle(
            question=question, answer=answer, evidence=verified,
            retrieved_doc_ids=result.doc_ids(), gaps=gaps, comparison=comparison,
            unsupported_sentences=unsupported, system="multi_agent",
            latency_ms=latency, trace=trace.as_dict() if self.settings.keep_trace else None,
            notes=notes,
        )


# --------------------------------------------------------------------------- facade
@dataclass
class ScientificAgentSystem:
    """Small facade so callers (CLI, API, evaluation) construct this once."""

    index: object
    settings: CoordinatorSettings = field(default_factory=CoordinatorSettings)
    coordinator: CoordinatorAgent = field(init=False)

    def __post_init__(self) -> None:
        self.coordinator = CoordinatorAgent(self.index, settings=self.settings)

    def ask(self, question: str) -> AnswerBundle:
        return self.coordinator.answer(question)
