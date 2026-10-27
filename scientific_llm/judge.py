"""scientific_llm/judge.py
========================
The independent judge used by the evaluation runner.

A system that validates its own citations cannot be trusted to score them. So the
evaluator re-derives support from the corpus for *every* system, using the same
rules and no access to the system's own flags:

* a citation is **supported** when its quotation really appears in the chunk it
  names (verbatim, or ≥90% of its terms present);
* a claim is **grounded** when at least one of its citation markers is supported
  *and* the claim shares enough terms with that quotation (≥0.45);
* a claim with no marker is grounded only if it is connective text (a lead-in),
  which is decided by the same rule the metric module uses.

This is what makes the hallucination number in the report a measurement rather
than a self-assessment.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from scientific_llm.metrics import CITATION_FREE_PREFIXES, claim_sentences
from scientific_llm.models import AnswerBundle
from scientific_llm.text import normalize_whitespace, overlap_ratio, terms

CITATION_MARKER = __import__("re").compile(r"\[(E\d+)\]")
SUPPORT_THRESHOLD = 0.45
QUOTE_COVERAGE_FLOOR = 0.9


@dataclass
class Judgement:
    citations_offered: int
    citations_supported: int
    claims: int
    claims_grounded: int
    unsupported_claims: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def citation_support(self) -> float:
        if not self.citations_offered:
            return 1.0
        return self.citations_supported / self.citations_offered

    @property
    def groundedness(self) -> float:
        if not self.claims:
            return 1.0
        return self.claims_grounded / self.claims

    @property
    def hallucination_rate(self) -> float:
        return 1.0 - self.groundedness

    def as_dict(self) -> dict[str, object]:
        return {
            "citations_offered": self.citations_offered,
            "citations_supported": self.citations_supported,
            "citation_support": round(self.citation_support, 4),
            "claims": self.claims,
            "claims_grounded": self.claims_grounded,
            "groundedness": round(self.groundedness, 4),
            "hallucination_rate": round(self.hallucination_rate, 4),
            "unsupported_claims": self.unsupported_claims[:5],
        }


class Judge:
    """Independently scores a bundle against the corpus."""

    def __init__(self, index) -> None:
        self.index = index

    def quote_supported(self, quote: str, chunk_id: str) -> bool:
        chunk = self.index.chunk(chunk_id)
        if chunk is None or not quote.strip():
            return False
        if normalize_whitespace(quote).lower() in normalize_whitespace(chunk.text).lower():
            return True
        coverage = overlap_ratio(set(terms(quote)), set(terms(chunk.text)))
        return coverage >= QUOTE_COVERAGE_FLOOR

    def assess(self, bundle: AnswerBundle) -> Judgement:
        supported_ids: set[str] = set()
        offered = 0
        for item in bundle.evidence:
            offered += 1
            if self.quote_supported(item.quote, item.chunk_id):
                supported_ids.add(item.evidence_id)

        quotes = {item.evidence_id: item.quote for item in bundle.evidence}
        claims = claim_sentences(bundle.answer)
        grounded = 0
        unsupported: list[str] = []

        for claim in claims:
            markers = CITATION_MARKER.findall(claim)
            if not markers:
                lowered = claim.lower()
                if any(lowered.startswith(prefix) for prefix in CITATION_FREE_PREFIXES):
                    grounded += 1
                    continue
                unsupported.append(claim)
                continue
            claim_terms = set(terms(claim))
            ok = False
            for marker in markers:
                if marker not in supported_ids:
                    continue
                quote_terms = set(terms(quotes.get(marker, "")))
                if overlap_ratio(quote_terms, claim_terms) >= SUPPORT_THRESHOLD:
                    ok = True
                    break
            grounded += 1 if ok else 0
            if not ok:
                unsupported.append(claim)

        notes: list[str] = []
        if offered and not supported_ids:
            notes.append("no citation could be matched to its source chunk")
        if claims and not grounded:
            notes.append("no claim is grounded by a supported citation")

        return Judgement(citations_offered=offered,
                         citations_supported=len(supported_ids),
                         claims=len(claims), claims_grounded=grounded,
                         unsupported_claims=unsupported, notes=notes)
