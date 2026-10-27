"""scientific_llm/ingest.py
==========================
Document ingestion (roadmap item 2): PDF, Markdown, plain text, and metadata from
science APIs (arXiv Atom/JSON, Crossref JSON).

Every ingester returns a :class:`ScientificDocument` and nothing else, so the rest
of the stack never has to care where a paper came from. Two rules hold:

* **the id is content-addressed** - ``doc_id`` derives from the title plus a short
  hash of the text, so re-ingesting a revised file replaces rather than duplicates;
* **metadata is never invented** - a missing DOI stays ``None``; the parser will not
  guess a venue from a filename.

The front-matter reader accepts both YAML-ish ``key: value`` blocks and a leading
``Title:/Authors:/Year:`` header, because that is what people actually write.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree

from scientific_llm import pdf as pdf_module
from scientific_llm.chunking import classify_section, sections_from_text
from scientific_llm.models import (
    DocumentMetadata,
    ScientificDocument,
    Section,
    SourceKind,
)
from scientific_llm.text import normalize_whitespace, sha256_text, slugify

SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt", ".text", ".rst", ".json", ".xml"}
DEFAULT_CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "scientific_corpus"


class IngestionError(RuntimeError):
    """Raised when a file or payload cannot be turned into a document."""


# --------------------------------------------------------------------------- ids
def make_doc_id(title: str, text: str) -> str:
    """Stable, readable id: ``retrieval-augmented-generation-<hash8>``."""
    return f"{slugify(title) or 'document'}-{sha256_text(text)[:8]}"


# --------------------------------------------------------------------------- front matter
_FRONT_MATTER_KEYS = {
    "title": "title", "authors": "authors", "author": "authors", "year": "year",
    "date": "year", "venue": "venue", "journal": "venue", "conference": "venue",
    "doi": "doi", "url": "url", "link": "url", "keywords": "keywords",
    "tags": "keywords", "abstract": "abstract", "license": "license",
}


def parse_front_matter(text: str) -> tuple[dict[str, object], str]:
    """Split optional metadata header from the body.

    Supports a ``---`` fenced block **and** a bare leading header of ``Key: value``
    lines. Returns ``(metadata, body)``.
    """
    raw = (text or "").replace("\r\n", "\n")
    metadata: dict[str, object] = {}

    if raw.lstrip().startswith("---"):
        trimmed = raw.lstrip()
        end = trimmed.find("\n---", 3)
        if end != -1:
            block = trimmed[3:end].strip()
            body = trimmed[end + 4:]
            metadata = _parse_key_value_lines(block)
            return metadata, body.lstrip("\n")

    lines = raw.split("\n")
    consumed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            consumed += 1
            break
        key, separator, value = stripped.partition(":")
        if not separator or key.strip().lower() not in _FRONT_MATTER_KEYS:
            break
        metadata[_FRONT_MATTER_KEYS[key.strip().lower()]] = value.strip()
        consumed += 1
    if metadata:
        return metadata, "\n".join(lines[consumed:])
    return {}, raw


def _parse_key_value_lines(block: str) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for line in block.split("\n"):
        key, separator, value = line.partition(":")
        if not separator:
            continue
        canonical = _FRONT_MATTER_KEYS.get(key.strip().lower())
        if canonical:
            metadata[canonical] = value.strip().strip('"').strip("'")
    return metadata


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value)
    parts = re.split(r"[;,]| and ", text)
    return [part.strip() for part in parts if part.strip()]


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


# --------------------------------------------------------------------------- markdown/text
def ingest_markdown(text: str, *, source: SourceKind = "markdown",
                    fallback_title: str | None = None) -> ScientificDocument:
    header, body = parse_front_matter(text)
    title = str(header.get("title") or "").strip()
    if not title:
        heading = re.search(r"^\s*#\s+(.+)$", body, re.MULTILINE)
        title = heading.group(1).strip() if heading else (fallback_title or "")
    if not title:
        raise IngestionError("could not determine a title (add 'title:' or a '# Heading')")

    sections = sections_from_text(body)
    if not sections:
        raise IngestionError("the document has no text")

    metadata = _metadata_from_header(header, title, sections, source=source)
    raw_text = normalize_whitespace(body)
    return ScientificDocument(
        doc_id=make_doc_id(title, raw_text), metadata=metadata, sections=sections,
        raw_text=raw_text, sha256=sha256_text(raw_text),
    )


def ingest_text(text: str, *, title: str,
                source: SourceKind = "text") -> ScientificDocument:
    """Plain text: one section, or ``ABSTRACT``/``1 INTRODUCTION`` splitting if seen."""
    body = normalize_whitespace(text)
    if not body:
        raise IngestionError("the document is empty")
    sections = _sections_from_plain_text(body)
    metadata = DocumentMetadata(title=title, source=source, abstract=(
        sections[0].text if sections and sections[0].label == "abstract" else None))
    return ScientificDocument(doc_id=make_doc_id(title, body), metadata=metadata,
                              sections=sections, raw_text=body,
                              sha256=sha256_text(body))


def _sections_from_plain_text(text: str) -> list[Section]:
    pattern = re.compile(
        r"^(?P<heading>(?:ABSTRACT|Abstract|\d+(?:\.\d+)*\s+[A-Z][A-Za-z ,&/-]{2,60}))\.?\s*$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return [Section(heading="Body", level=1, text=text,
                        label=classify_section("Body"))]
    sections: list[Section] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group("heading").strip()
        body = text[start:end].strip()
        if body:
            sections.append(Section(heading=heading, level=1, text=body,
                                    label=classify_section(heading)))
    return sections


def _metadata_from_header(header: dict[str, object], title: str,
                          sections: list[Section], *, source: str) -> DocumentMetadata:
    abstract = str(header.get("abstract") or "").strip()
    if not abstract:
        for section in sections:
            if section.label == "abstract":
                abstract = section.text.strip()[:1500]
                break
    return DocumentMetadata(
        title=title,
        authors=_as_list(header.get("authors")),
        year=_as_int(header.get("year")),
        venue=str(header["venue"]).strip() if header.get("venue") else None,
        doi=str(header["doi"]).strip() if header.get("doi") else None,
        url=str(header["url"]).strip() if header.get("url") else None,
        abstract=abstract or None,
        keywords=_as_list(header.get("keywords")),
        source=source,                                  # type: ignore[arg-type]
        license=str(header["license"]).strip() if header.get("license") else None,
    )


# --------------------------------------------------------------------------- pdf
def ingest_pdf(data: bytes | str, *, title: str | None = None,
               metadata: DocumentMetadata | None = None) -> ScientificDocument:
    """Extract text from a PDF and infer sections from its headings."""
    extracted = pdf_module.extract_text(data)
    text = extracted.text
    sections = _sections_from_pdf_text(text)
    if metadata is None:
        if not title:
            title = _first_line_as_title(text)
        metadata = DocumentMetadata(title=title, source="pdf",
                                    abstract=_guess_abstract(sections))
    raw_text = normalize_whitespace(text)
    return ScientificDocument(doc_id=make_doc_id(metadata.title, raw_text),
                              metadata=metadata, sections=sections,
                              raw_text=raw_text, sha256=sha256_text(raw_text))


_PDF_HEADING = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*)\.?\s+)?(abstract|introduction|related work|background|"
    r"methods?|methodology|approach|experimental setup|experiments?|results?|"
    r"evaluation|discussion|limitations?|future work|conclusions?|references)\s*$",
    re.IGNORECASE,
)


def _sections_from_pdf_text(text: str) -> list[Section]:
    lines = text.split("\n")
    sections: list[Section] = []
    buffer: list[str] = []
    heading = "Body"
    found_heading = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(Section(heading=heading, level=1, text=body,
                                    label=classify_section(heading)))
        buffer.clear()

    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) <= 60 and _PDF_HEADING.match(stripped):
            if found_heading or buffer:
                flush()
            heading, found_heading = stripped, True
            continue
        buffer.append(line)
    flush()
    return sections or [Section(heading="Body", level=1, text=text, label="other")]


def _first_line_as_title(text: str) -> str:
    for line in text.split("\n"):
        candidate = line.strip()
        if 5 <= len(candidate) <= 200:
            return candidate
    return "Untitled document"


def _guess_abstract(sections: list[Section]) -> str | None:
    for section in sections:
        if section.label == "abstract":
            return section.text[:1500]
    return None


# --------------------------------------------------------------------------- APIs
def ingest_arxiv_payload(payload: dict | str) -> list[ScientificDocument]:
    """arXiv metadata (JSON export or Atom XML string)."""
    if isinstance(payload, str) and payload.lstrip().startswith("<"):
        return _arxiv_from_atom(payload)
    data = payload if isinstance(payload, dict) else json.loads(payload)
    entries = data.get("entries") or data.get("items") or data.get("results") or []
    if isinstance(entries, dict):
        entries = [entries]
    documents = []
    for entry in entries:
        title = normalize_whitespace(str(entry.get("title") or ""))
        if not title:
            continue
        abstract = normalize_whitespace(str(entry.get("summary") or entry.get("abstract") or ""))
        authors = _arxiv_authors(entry)
        published = entry.get("published") or entry.get("updated") or ""
        keywords = entry.get("categories") or entry.get("keywords") or []
        sections = [Section(heading="Abstract", level=1, text=abstract, label="abstract")] \
            if abstract else []
        body = entry.get("full_text") or entry.get("text")
        if body:
            sections.extend(sections_from_text(str(body)))
        raw_text = "\n\n".join(section.text for section in sections)
        metadata = DocumentMetadata(
            title=title, authors=authors, year=_as_int(published),
            venue="arXiv", doi=_arxiv_doi(entry), url=str(entry.get("id") or "") or None,
            abstract=abstract or None, keywords=_as_list(keywords), source="arxiv",
        )
        documents.append(ScientificDocument(
            doc_id=make_doc_id(title, raw_text or title), metadata=metadata,
            sections=sections or [Section(heading="Abstract", text=title, label="abstract")],
            raw_text=normalize_whitespace(raw_text or title),
            sha256=sha256_text(raw_text or title)))
    if not documents:
        raise IngestionError("no usable entries in that arXiv payload")
    return documents


def _arxiv_authors(entry: dict) -> list[str]:
    authors = entry.get("authors") or []
    names = []
    for author in authors:
        if isinstance(author, dict):
            names.append(str(author.get("name") or "").strip())
        else:
            names.append(str(author).strip())
    return [name for name in names if name]


def _arxiv_doi(entry: dict) -> str | None:
    doi = entry.get("doi")
    if doi:
        return str(doi)
    comment = str(entry.get("comment") or "")
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", comment)
    return match.group(0) if match else None


def _arxiv_from_atom(xml_text: str) -> list[ScientificDocument]:
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    root = ElementTree.fromstring(xml_text)
    entries = []
    for entry in root.findall("atom:entry", namespace):
        entries.append({
            "title": (entry.findtext("atom:title", default="", namespaces=namespace) or "").strip(),
            "summary": (entry.findtext("atom:summary", default="", namespaces=namespace) or "").strip(),
            "published": entry.findtext("atom:published", default="", namespaces=namespace),
            "id": entry.findtext("atom:id", default="", namespaces=namespace),
            "authors": [{"name": (author.findtext("atom:name", default="", namespaces=namespace)
                                  or "").strip()}
                        for author in entry.findall("atom:author", namespace)],
            "categories": [category.get("term", "") for category in
                           entry.findall("atom:category", namespace)],
        })
    return ingest_arxiv_payload({"entries": entries})


def ingest_crossref_payload(payload: dict | str) -> list[ScientificDocument]:
    """Crossref works API (``message.items[]``)."""
    data = payload if isinstance(payload, dict) else json.loads(payload)
    items = data.get("message", {}).get("items") if "message" in data else data.get("items")
    items = items or []
    documents = []
    for item in items:
        title = _first_of(item.get("title")) or ""
        if not title.strip():
            continue
        abstract = re.sub(r"<[^>]+>", " ", str(item.get("abstract") or ""))
        abstract = normalize_whitespace(abstract)
        authors = []
        for author in item.get("author") or []:
            given = str(author.get("given") or "").strip()
            family = str(author.get("family") or "").strip()
            name = " ".join(part for part in (given, family) if part)
            if name:
                authors.append(name)
        issued = item.get("issued", {}).get("date-parts") or [[None]]
        year = issued[0][0] if issued and issued[0] else None
        sections = [Section(heading="Abstract", level=1, text=abstract, label="abstract")] \
            if abstract else [Section(heading="Abstract", level=1, text=title, label="abstract")]
        raw_text = "\n\n".join(section.text for section in sections)
        metadata = DocumentMetadata(
            title=normalize_whitespace(title), authors=authors,
            year=int(year) if year else None, venue=_first_of(item.get("container-title")),
            doi=item.get("DOI"), url=item.get("URL"), abstract=abstract or None,
            keywords=_as_list(item.get("subject")), source="crossref",
            license=_first_of((item.get("license") or [{}])[0].get("URL")
                              if item.get("license") else None),
        )
        documents.append(ScientificDocument(
            doc_id=make_doc_id(metadata.title, raw_text), metadata=metadata,
            sections=sections, raw_text=normalize_whitespace(raw_text),
            sha256=sha256_text(raw_text)))
    if not documents:
        raise IngestionError("no usable entries in that Crossref payload")
    return documents


def _first_of(value: object) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None


# --------------------------------------------------------------------------- dispatch
def detect_api_source(payload: dict | str) -> str:
    if isinstance(payload, str) and payload.lstrip().startswith("<"):
        return "arxiv"
    data = payload if isinstance(payload, dict) else json.loads(payload)
    if "message" in data:
        return "crossref"
    if any(key in data for key in ("entries", "feed", "items", "results")):
        return "arxiv"
    raise IngestionError("unrecognised API payload: expected arXiv or Crossref metadata")


def ingest_api_payload(payload: dict | str) -> list[ScientificDocument]:
    source = detect_api_source(payload)
    return (ingest_arxiv_payload(payload) if source == "arxiv"
            else ingest_crossref_payload(payload))


def ingest_path(path: str | Path, *, title: str | None = None) -> list[ScientificDocument]:
    """Ingest one file, dispatching on its suffix."""
    file_path = Path(path)
    if not file_path.is_file():
        raise IngestionError(f"not a file: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestionError(
            f"unsupported file type '{suffix}'; supported: "
            + ", ".join(sorted(SUPPORTED_SUFFIXES)))

    if suffix == ".pdf":
        return [ingest_pdf(str(file_path), title=title)]
    if suffix in {".md", ".markdown"}:
        return [ingest_markdown(file_path.read_text(encoding="utf-8", errors="replace"),
                                source="markdown", fallback_title=file_path.stem)]
    if suffix in {".txt", ".text", ".rst"}:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return [ingest_text(text, title=title or file_path.stem)]
    payload = file_path.read_text(encoding="utf-8")
    return ingest_api_payload(json.loads(payload) if suffix == ".json" else payload)


def ingest_directory(directory: str | Path) -> list[ScientificDocument]:
    """Ingest every supported file directly inside *directory* (sorted, stable)."""
    root = Path(directory)
    if not root.is_dir():
        raise IngestionError(f"not a directory: {root}")
    documents: list[ScientificDocument] = []
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            documents.extend(ingest_path(path))
    return documents
