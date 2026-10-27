"""scientific_llm/chunking.py
===========================
Section-aware chunking (roadmap item 3).

Why not a fixed 512-token window over the whole paper? Because in a paper,
*position is meaning*: a sentence in **Methods** is a description of what was done,
the same sentence in **Limitations** is an admission about it. Flattening the
document throws that away, and a retriever that cannot say "this came from
Limitations" cannot answer "what are the open problems?".

So the chunker:

1. never crosses a section boundary;
2. packs whole paragraphs until the budget is reached (no mid-sentence starts);
3. carries a configurable overlap *of trailing sentences* so a claim split across
   paragraphs is still retrievable;
4. labels each chunk with its section, so the retriever can apply a section prior.

Section labels come from :func:`classify_section`, which understands the usual
paper headings, numbered headings (``3.1 Method``), and common aliases
("Experimental Setup" -> methods, "Results and Discussion" -> results).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from scientific_llm.models import CANONICAL_SECTIONS, Chunk, ScientificDocument, Section
from scientific_llm.text import sentences, tokenize

DEFAULT_TARGET_TOKENS = 220
DEFAULT_OVERLAP_TOKENS = 45
DEFAULT_MIN_TOKENS = 40

_ALIASES: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "summary"),
    "introduction": ("introduction", "motivation", "overview"),
    "related work": ("related work", "related works", "prior work", "background and related"),
    "background": ("background", "preliminaries", "theory"),
    "methods": ("method", "methods", "methodology", "approach", "experimental setup",
                "experiment", "experiments", "materials and methods", "proposed method",
                "system design", "implementation"),
    "results": ("result", "results", "results and discussion", "evaluation",
                "experimental results", "findings", "analysis"),
    "discussion": ("discussion", "implications", "interpretation"),
    "limitations": ("limitation", "limitations", "threats to validity", "weaknesses"),
    "future work": ("future work", "future directions", "open problems",
                    "future research"),
    "conclusion": ("conclusion", "conclusions", "concluding remarks", "summary and conclusion"),
    "references": ("references", "bibliography", "works cited"),
}

_HEADING_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+")


def classify_section(heading: str) -> str:
    """Map an arbitrary heading to a canonical label (or ``"other"``)."""
    cleaned = _HEADING_NUMBER.sub("", (heading or "").strip()).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    for label in CANONICAL_SECTIONS:
        if cleaned == label:
            return label
    for label, aliases in _ALIASES.items():
        for alias in aliases:
            if cleaned == alias or cleaned.startswith(alias + " ") or cleaned.endswith(" " + alias):
                return label
    for label, aliases in _ALIASES.items():
        if any(alias in cleaned for alias in aliases):
            return label
    return "other"


@dataclass
class ChunkingConfig:
    target_tokens: int = DEFAULT_TARGET_TOKENS
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS
    min_tokens: int = DEFAULT_MIN_TOKENS

    def __post_init__(self) -> None:
        if self.target_tokens < 40:
            raise ValueError("target_tokens must be at least 40")
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")


def chunk_document(document: ScientificDocument,
                   config: ChunkingConfig | None = None) -> list[Chunk]:
    """Split *document* into section-bounded :class:`Chunk` objects."""
    config = config or ChunkingConfig()
    chunks: list[Chunk] = []

    for section_index, section in enumerate(document.sections):
        label = section.label or classify_section(section.heading)
        for ordinal, text in enumerate(_pack_section(section.text, config)):
            chunk = Chunk(
                chunk_id=f"{document.doc_id}::{slug(section.heading)}::{ordinal}",
                doc_id=document.doc_id,
                section_heading=section.heading,
                section_label=label,
                ordinal=ordinal,
                text=text,
                token_count=len(tokenize(text, keep_stopwords=True)),
                starts_mid_sentence=not text[:1].isupper() and not text[:1].isdigit(),
            )
            chunks.append(chunk)
    return chunks


def _pack_section(text: str, config: ChunkingConfig) -> list[str]:
    """Pack paragraphs (fallback: sentences) into budget-sized chunks."""
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text or "") if block.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(tokenize(paragraph, keep_stopwords=True)) <= config.target_tokens:
            units.append(paragraph)
            continue
        units.extend(_split_long_paragraph(paragraph, config.target_tokens))

    packed: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        body = "\n\n".join(current).strip()
        if packed and len(tokenize(body, keep_stopwords=True)) < config.min_tokens:
            packed[-1] = f"{packed[-1]}\n\n{body}".strip()       # merge tail fragments
        else:
            packed.append(body)
        current, current_tokens = [], 0

    for unit in units:
        unit_tokens = len(tokenize(unit, keep_stopwords=True))
        if current and current_tokens + unit_tokens > config.target_tokens:
            overlap = _tail(current, config.overlap_tokens)
            flush()
            if overlap:
                current = [overlap]
                current_tokens = len(tokenize(overlap, keep_stopwords=True))
        current.append(unit)
        current_tokens += unit_tokens

    flush()
    return [chunk for chunk in packed if chunk.strip()]


def _split_long_paragraph(paragraph: str, target: int) -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    buffer_tokens = 0
    for sentence in sentences(paragraph):
        sentence_tokens = len(tokenize(sentence, keep_stopwords=True))
        if buffer and buffer_tokens + sentence_tokens > target:
            parts.append(" ".join(buffer))
            buffer, buffer_tokens = [], 0
        buffer.append(sentence)
        buffer_tokens += sentence_tokens
    if buffer:
        parts.append(" ".join(buffer))
    return parts


def _tail(units: list[str], budget: int) -> str:
    """Trailing sentences worth *budget* tokens, used as chunk overlap."""
    if budget <= 0:
        return ""
    collected: list[str] = []
    used = 0
    for unit in reversed(units):
        for sentence in reversed(sentences(unit)):
            size = len(tokenize(sentence, keep_stopwords=True))
            if used + size > budget:
                return " ".join(collected).strip()
            collected.insert(0, sentence)
            used += size
    return " ".join(collected).strip()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "section"


def sections_from_text(text: str, *, default_heading: str = "Body") -> list[Section]:
    """Build sections from Markdown-ish text (used by the markdown ingester).

    Headings are ``#``-prefixed lines; everything before the first heading becomes
    the ``default_heading`` section (usually the abstract).
    """
    sections: list[Section] = []
    buffer: list[str] = []
    heading, level = default_heading, 1

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if heading == default_heading and body:
            sections.append(Section(heading=heading, level=level, text=body,
                                    label="abstract"))
        elif body:
            sections.append(Section(heading=heading, level=level, text=body,
                                    label=classify_section(heading)))
        buffer.clear()

    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            candidate = stripped[hashes:].strip()
            if candidate:
                if buffer:
                    flush()
                heading, level = candidate, max(1, min(hashes, 6))
                continue
        buffer.append(line)
    flush()
    return [section for section in sections if section.text.strip()]
