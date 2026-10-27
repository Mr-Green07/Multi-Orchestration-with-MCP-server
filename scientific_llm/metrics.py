"""scientific_llm/metrics.py
==========================
Retrieval and answer metrics (roadmap items 10 and 21).

Retrieval
    ``recall_at_k``, ``mrr``, ``precision_at_k`` - the standard IR trio, computed
    against a gold set of document ids.

Answers
    ``citation_precision`` - share of cited evidence that really supports its claim
    (verified + quote actually in the chunk);
    ``citation_recall``    - share of gold papers that appear in the citations;
    ``relevance``          - overlap between the answer and the gold key points;
    ``hallucination_rate`` - share of answer sentences with no valid support. This
    is the number the whole citation-validation agent exists to move;
    ``latency_ms``, ``answer_length``.

Every metric is a pure function of (prediction, gold), so each is testable on tiny
hand-written examples - which is how a metric should be trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from scientific_llm.models import AnswerBundle
from scientific_llm.text import sentences, terms, tokenize


# --------------------------------------------------------------------------- retrieval
def recall_at_k(retrieved: list[str], gold: list[str], k: int = 5) -> float:
    if not gold:
        return 0.0
    return len(set(retrieved[:k]) & set(gold)) / len(set(gold))


def precision_at_k(retrieved: list[str], gold: list[str], k: int = 5) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    return len(set(top) & set(gold)) / len(set(top))


def reciprocal_rank(retrieved: list[str], gold: list[str]) -> float:
    gold_set = set(gold)
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in gold_set:
            return 1.0 / rank
    return 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# --------------------------------------------------------------------------- answers
@dataclass
class AnswerMetrics:
    citation_precision: float
    citation_recall: float
    relevance: float
    hallucination_rate: float
    unsupported_sentences: int
    claims: int
    citation_count: int
    answer_length: int
    latency_ms: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "citation_precision": round(self.citation_precision, 4),
            "citation_recall": round(self.citation_recall, 4),
            "relevance": round(self.relevance, 4),
            "hallucination_rate": round(self.hallucination_rate, 4),
            "unsupported_sentences": self.unsupported_sentences,
            "claims": self.claims,
            "citation_count": self.citation_count,
            "answer_length": self.answer_length,
            "latency_ms": round(self.latency_ms, 2),
        }


#: Sentences that merely introduce or label the answer, not claims about the world.
NON_CLAIM_PREFIXES = (
    "across ", "the evidence", "sources", "evidence", "context retrieved",
    "methodology comparison", "limitations and open questions", "open questions",
    "the corpus does not",
)


def claim_sentences(answer: str) -> list[str]:
    """Sentences that assert something about the world (shared with the validator).

    Lines are split first because answers are bulleted: a bullet is one claim, and
    treating the whole answer as one sentence would make every metric meaningless.
    """
    claims: list[str] = []
    for raw_line in (answer or "").split("\n"):
        line = raw_line.strip().lstrip("-*").strip()
        if not line:
            continue
        # A bullet that ends with a citation *is* one claim: splitting it would put
        # the marker in a different sentence from the assertion it supports.
        if _MARKER.search(line):
            if _is_claim(line):
                claims.append(line)
            continue
        for sentence in sentences(line) or [line]:
            if _is_claim(sentence):
                claims.append(sentence.strip())
    return claims


_MARKER = re.compile(r"\[E\d+\]")

#: Public alias used by the independent judge.
CITATION_FREE_PREFIXES = NON_CLAIM_PREFIXES


def _is_claim(sentence: str) -> bool:
    token_count = len(tokenize(sentence))
    if token_count < 5:
        return False
    lowered = sentence.strip().lower()
    if any(lowered.startswith(prefix) for prefix in NON_CLAIM_PREFIXES):
        return False
    if lowered.endswith(":"):
        return False
    return True


def citation_precision(bundle: AnswerBundle) -> float:
    """Verified citations / all citations offered (1.0 when nothing is cited)."""
    if not bundle.evidence:
        return 1.0
    good = [item for item in bundle.evidence
            if item.verified and item.support in {"direct", "paraphrase"}]
    return len(good) / len(bundle.evidence)


def citation_recall(bundle: AnswerBundle, gold_docs: list[str]) -> float:
    if not gold_docs:
        return 0.0
    cited = {item.doc_id for item in bundle.evidence}
    return len(cited & set(gold_docs)) / len(set(gold_docs))


def relevance(bundle: AnswerBundle, key_points: list[str]) -> float:
    """Fraction of gold key points that the answer covers (chance-corrected)."""
    if not key_points:
        return 0.0
    answer_terms = set(terms(bundle.answer))
    covered = 0
    for point in key_points:
        point_terms = set(terms(point))
        if not point_terms:
            continue
        if len(point_terms & answer_terms) / len(point_terms) >= 0.6:
            covered += 1
    return covered / len(key_points)


def supported_fraction(bundle: AnswerBundle) -> float:
    """Share of claim sentences the bundle says are backed by verified evidence."""
    claims = claim_sentences(bundle.answer)
    if not claims:
        return 1.0
    unsupported = min(len(bundle.unsupported_sentences), len(claims))
    return max(0.0, 1.0 - unsupported / len(claims))


def hallucination_rate(bundle: AnswerBundle) -> tuple[float, int, int]:
    """Unsupported claims / claims, with both counts for the report table."""
    claims = len(claim_sentences(bundle.answer))
    unsupported = min(len(bundle.unsupported_sentences), claims)
    if claims == 0:
        return 0.0, 0, 0
    return unsupported / claims, unsupported, claims


def evaluate_answer(bundle: AnswerBundle, *, gold_docs: list[str] | None = None,
                    key_points: list[str] | None = None) -> AnswerMetrics:
    rate, unsupported, claims = hallucination_rate(bundle)
    return AnswerMetrics(
        citation_precision=citation_precision(bundle),
        citation_recall=citation_recall(bundle, gold_docs or []),
        relevance=relevance(bundle, key_points or []),
        hallucination_rate=rate,
        unsupported_sentences=unsupported,
        claims=claims,
        citation_count=len([item for item in bundle.evidence if item.verified]),
        answer_length=len((bundle.answer or "").split()),
        latency_ms=bundle.latency_ms,
    )


def aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
    """Mean of every numeric column (used by the report tables)."""
    if not rows:
        return {}
    keys = [key for key, value in rows[0].items() if isinstance(value, (int, float))]
    return {key: round(mean([float(row.get(key, 0.0)) for row in rows]), 4) for key in keys}
