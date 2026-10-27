"""scientific_llm/pdf.py
======================
PDF text extraction with **no mandatory dependency**.

``pypdf``/``PyPDF2`` are used when present (they handle the long tail of real PDFs).
When they are not, the built-in reader below does the job for the common case:
uncompressed or Flate-compressed content streams, text shown with ``Tj``/``TJ``/
``'``/``"`` operators, WinAnsi/Latin-1 strings, and the standard ``\\ooo`` octal and
``\\n``-style escapes that LaTeX-produced PDFs use constantly.

What it deliberately does *not* do: OCR, embedded font CMaps for CJK, or
encrypted files. Those raise a clear :class:`PDFExtractionError` instead of
returning silently mangled text - a paper with half its characters missing is
worse than a paper that failed to load.

The matching *writer* lives in ``scripts/make_sample_pdf.py`` so tests can build a
real PDF from source text with no third-party tooling.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from scientific_llm.text import normalize_whitespace


class PDFExtractionError(RuntimeError):
    """Raised when a PDF cannot be turned into text."""


@dataclass
class PDFText:
    text: str
    pages: int
    backend: str
    encrypted: bool = False


# --------------------------------------------------------------------------- public
def extract_text(data: bytes | str) -> PDFText:
    """Extract text from PDF bytes (or a path). Raises :class:`PDFExtractionError`."""
    if isinstance(data, str):
        with open(data, "rb") as handle:
            raw = handle.read()
    else:
        raw = data
    if not raw.startswith(b"%PDF"):
        raise PDFExtractionError("that file does not start with %PDF")

    encrypted = b"/Encrypt" in raw
    if encrypted:
        raise PDFExtractionError(
            "the PDF is encrypted; decrypt it first (qpdf --decrypt) and retry"
        )

    backend_error: Exception | None = None
    try:
        result = _extract_with_pypdf(raw)
        if result is not None:
            return result
    except Exception as exc:                     # pypdf present but unhappy
        backend_error = exc

    try:
        return _extract_builtin(raw)
    except Exception as exc:
        raise PDFExtractionError(
            f"could not extract text from this PDF: {exc}"
            + (f" (pypdf said: {backend_error})" if backend_error else "")
        ) from exc


def looks_like_prose(text: str, minimum_ratio: float = 0.5) -> bool:
    """Cheap sanity check that extraction produced words, not binary noise."""
    if not text:
        return False
    letters = sum(1 for char in text if char.isalpha() or char.isspace())
    return (letters / len(text)) >= minimum_ratio


# --------------------------------------------------------------------------- pypdf
def _extract_with_pypdf(raw: bytes) -> PDFText:
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError:
        try:
            import PyPDF2 as pypdf  # type: ignore[import-not-found,no-redef]
        except ImportError as exc:
            raise PDFExtractionError("pypdf is not installed") from exc

    import io

    reader = pypdf.PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:                             # one bad page is not fatal
            pages.append("")
    text = normalize_whitespace("\n\n".join(pages))
    if not looks_like_prose(text):
        raise PDFExtractionError("pypdf returned no usable text")
    return PDFText(text=text, pages=len(pages), backend="pypdf")


# --------------------------------------------------------------------------- builtin
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_TEXT_OP_RE = re.compile(
    rb"\((?:\\.|[^\\()])*\)\s*(?:Tj|TJ|'|\")|\[(?:[^\[\]]|\\.)*\]\s*TJ", re.DOTALL
)
_PAGE_RE = re.compile(rb"/Type\s*/Page[^s]")


def _extract_builtin(raw: bytes) -> PDFText:
    pages = len(_PAGE_RE.findall(raw)) or 1
    pieces: list[str] = []

    for match in _STREAM_RE.finditer(raw):
        body = match.group(1)
        decoded = _maybe_inflate(body)
        if decoded is None:
            continue
        for operand in _TEXT_OP_RE.finditer(decoded):
            fragment = _operand_to_text(operand.group(0))
            if fragment:
                pieces.append(fragment)

    text = normalize_whitespace("\n".join(pieces))
    if not text:
        raise PDFExtractionError(
            "no text operators found; the PDF is probably scanned (needs OCR)"
        )
    return PDFText(text=text, pages=pages, backend="builtin")


def _maybe_inflate(body: bytes) -> bytes | None:
    if b"FlateDecode" in body[:200] or body[:2] not in (b"(", b"["):
        try:
            return zlib.decompress(body)
        except zlib.error:
            pass
    # Some producers store the content stream uncompressed.
    if b"BT" in body and b"ET" in body:
        return body
    try:
        return zlib.decompress(body)
    except zlib.error:
        return None


def _operand_to_text(operand: bytes) -> str:
    """Turn one text-showing operator into a plain string."""
    chunks: list[str] = []
    if operand.startswith(b"["):                      # TJ array: (a) -20 (b)
        for literal in re.finditer(rb"\((?:\\.|[^\\()])*\)", operand):
            chunks.append(_decode_pdf_string(literal.group(0)[1:-1]))
        return "".join(chunks)
    match = re.match(rb"\((?:\\.|[^\\()])*\)", operand)
    if match:
        return _decode_pdf_string(match.group(0)[1:-1])
    return ""


_ESCAPES = {
    b"n": "\n", b"r": "\n", b"t": "\t", b"b": "", b"f": "", b"(": "(", b")": ")",
    b"\\": "\\",
}


def _decode_pdf_string(body: bytes) -> str:
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index:index + 1]
        if char != b"\\":
            out.append(char.decode("latin-1"))
            index += 1
            continue
        nxt = body[index + 1:index + 2]
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            index += 2
            continue
        octal = re.match(rb"[0-7]{1,3}", body[index + 1:index + 4])
        if octal:
            out.append(chr(int(octal.group(0), 8)))
            index += 1 + len(octal.group(0))
            continue
        index += 2
    return "".join(out)
