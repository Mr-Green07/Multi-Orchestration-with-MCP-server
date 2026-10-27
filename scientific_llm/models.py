"""scientific_llm/models.py
=========================
The data contract for the whole scientific stack.

Five objects, each with a reason to exist:

* :class:`DocumentMetadata` - the bibliographic record (item 1 of the roadmap:
  "scientific document and metadata schema");
* :class:`Section` / :class:`ScientificDocument` - a paper split by structure, not
  by character count, because *where* a sentence sits changes what it means;
* :class:`Chunk` - the retrievable unit, always pointing back at its section;
* :class:`Evidence` - the only thing an answer is allowed to cite: a verbatim
  quote plus the provenance needed to check it.

Every model is a pydantic model, so the JSON that goes over the HTTP API, into
SQLite and out of the benchmark report is validated at the boundary.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

#: Canonical section labels. Anything unrecognised is kept verbatim but ranked
#: below these when the retriever applies its section prior.
CANONICAL_SECTIONS = (
    "abstract", "introduction", "related work", "background", "methods", "results",
    "discussion", "limitations", "future work", "conclusion", "references",
)


SourceKind = Literal["pdf", "markdown", "text", "arxiv", "crossref", "manual"]


class DocumentMetadata(BaseModel):
    """Bibliographic record. Everything except ``title`` is optional by design."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    keywords: list[str] = Field(default_factory=list)
    source: SourceKind = "manual"
    license: str | None = None
    language: str = "en"

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("a scientific document needs a title")
        return cleaned

    @field_validator("year")
    @classmethod
    def _plausible_year(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not 1500 <= int(value) <= 2100:
            raise ValueError(f"implausible publication year: {value}")
        return int(value)


class Section(BaseModel):
    """One structural block of a paper."""

    heading: str
    level: int = 1
    text: str = ""
    label: str = "other"

    @property
    def is_canonical(self) -> bool:
        return self.label in CANONICAL_SECTIONS


class ScientificDocument(BaseModel):
    """A parsed paper: metadata + ordered sections + the flat text."""

    doc_id: str
    metadata: DocumentMetadata
    sections: list[Section] = Field(default_factory=list)
    raw_text: str = ""
    sha256: str | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def year(self) -> int | None:
        return self.metadata.year

    def abstract(self) -> str:
        for section in self.sections:
            if section.label == "abstract":
                return section.text
        return self.metadata.abstract or ""

    def section_text(self, label: str) -> str:
        return "\n\n".join(section.text for section in self.sections
                           if section.label == label)

    def section_heading(self, label: str) -> str | None:
        for section in self.sections:
            if section.label == label:
                return section.heading
        return None

    def citations_line(self) -> str:
        """Human-readable short citation used in answers."""
        authors = self.metadata.authors
        if not authors:
            author_part = "Unknown authors"
        elif len(authors) == 1:
            author_part = authors[0]
        elif len(authors) == 2:
            author_part = f"{authors[0]} & {authors[1]}"
        else:
            author_part = f"{authors[0]} et al."
        year = f" ({self.metadata.year})" if self.metadata.year else ""
        return f"{author_part}{year}. {self.title}"


class Chunk(BaseModel):
    """Retrievable passage. ``ordinal`` is the position within its section."""

    chunk_id: str
    doc_id: str
    section_heading: str
    section_label: str
    ordinal: int
    text: str
    token_count: int = 0
    starts_mid_sentence: bool = False


Support = Literal["direct", "paraphrase", "weak"]


class Evidence(BaseModel):
    """A citable fact: one verified quotation plus its provenance.

    ``verified`` is filled in by :class:`scientific_llm.agents.CitationValidatorAgent`
    after it re-reads the source chunk - an Evidence object that has not been
    verified must never reach a user-facing answer.
    """

    evidence_id: str
    claim: str
    quote: str
    doc_id: str
    chunk_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    section: str = ""
    support: Support = "direct"
    score: float = 0.0
    verified: bool = False
    verification_note: str = ""

    def citation(self) -> str:
        authors = self.authors
        if not authors:
            named = "Unknown authors"
        elif len(authors) == 1:
            named = authors[0]
        elif len(authors) == 2:
            named = f"{authors[0]} & {authors[1]}"
        else:
            named = f"{authors[0]} et al."
        year = f", {self.year}" if self.year else ""
        return f"{named}{year}"

    def as_reference(self) -> str:
        return f"[{self.evidence_id}] {self.citation()} - {self.title} ({self.section})"


class AnswerBundle(BaseModel):
    """What every answering system returns, single- or multi-agent."""

    question: str
    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    comparison: list[dict] = Field(default_factory=list)
    unsupported_sentences: list[str] = Field(default_factory=list)
    system: str = "multi_agent"
    latency_ms: float = 0.0
    trace: dict | None = None
    notes: list[str] = Field(default_factory=list)

    def citations(self) -> list[str]:
        return [evidence.evidence_id for evidence in self.evidence if evidence.verified]

    def as_text(self) -> str:
        lines = [self.answer.strip()]
        if self.gaps:
            lines.append("")
            lines.append("Open questions / gaps")
            lines.extend(f"- {gap}" for gap in self.gaps)
        if self.evidence:
            lines.append("")
            lines.append("Evidence")
            lines.extend(evidence.as_reference() for evidence in self.evidence)
        return "\n".join(lines)
