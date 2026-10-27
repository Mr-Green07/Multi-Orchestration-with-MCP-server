#!/usr/bin/env python3
"""Write a real, minimal PDF from plain text - no third-party libraries.

Used by the tests (ingestion must be exercised against an actual PDF, not a mock) and
by anyone who wants to check that the built-in extractor works before trusting it
with a 40-page paper.

    python scripts/make_sample_pdf.py out.pdf "My Title" notes.txt
    python scripts/make_sample_pdf.py --builtin out.pdf notes.txt
"""
from __future__ import annotations

import zlib
from pathlib import Path


def _escape(text: str) -> bytes:
    encoded = text.encode("latin-1", "replace")
    encoded = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return encoded


def build_pdf(text: str, *, title: str = "Sample Scientific Paper",
              compress: bool = True) -> bytes:
    """Return PDF bytes containing *text*, one line per ``\\n``."""
    lines = [line.rstrip() for line in text.splitlines()]
    if not lines:
        lines = ["(empty)"]

    operations: list[str] = ["BT", "/F1 11 Tf", "13 TL", "50 780 Td"]
    for line in lines:
        operations.append(f"({_escape(line).decode('latin-1')}) Tj")
        operations.append("T*")
    operations.append("ET")
    stream = "\n".join(operations).encode("latin-1")

    filters = ""
    if compress:
        stream = zlib.compress(stream, 9)
        filters = "/Filter /FlateDecode "

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
         b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
        (f"<< /Length {len(stream)} {filters}>>".encode("ascii") + b"\nstream\n"
         + stream + b"\nendstream"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Title ({_escape(title).decode('latin-1')}) /Producer (make_sample_pdf) >>"
        .encode("latin-1"),
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_position = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
            f"startxref\n{xref_position}\n%%EOF\n").encode("ascii")
    return bytes(out)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="create a minimal text PDF")
    parser.add_argument("output")
    parser.add_argument("title", nargs="?", default="Sample Scientific Paper")
    parser.add_argument("source", nargs="?", default=None, help="text file (default: stdin)")
    parser.add_argument("--builtin", action="store_true",
                        help="write an uncompressed stream (exercises the raw reader path)")
    args = parser.parse_args(argv)

    if args.source:
        text = Path(args.source).read_text(encoding="utf-8")
    else:
        import sys

        text = sys.stdin.read()
    payload = build_pdf(text, title=args.title, compress=not args.builtin)
    Path(args.output).write_bytes(payload)
    print(f"{args.output}: {len(payload)} bytes, "
          f"{'uncompressed' if args.builtin else 'Flate stream'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
