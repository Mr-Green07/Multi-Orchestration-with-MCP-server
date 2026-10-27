#!/usr/bin/env python3
"""Build (or rebuild) the scientific corpus index.

    python scripts/build_corpus.py                     # bundled corpus -> default db
    python scripts/build_corpus.py data/papers --db database/mine.db
    python scripts/build_corpus.py --verify            # also check the index is usable

Exit codes: 0 ok, 1 ingestion problem, 2 usage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scientific_llm.index import DEFAULT_DB_PATH, CorpusIndex  # noqa: E402
from scientific_llm.ingest import IngestionError, ingest_directory  # noqa: E402
from scientific_llm.retrieval import HybridRetriever, RetrievalAgent  # noqa: E402

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "data" / "scientific_corpus"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build the scientific corpus index")
    parser.add_argument("corpus", nargs="?", default=str(DEFAULT_CORPUS))
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--reset", action="store_true", help="empty the index first")
    parser.add_argument("--verify", action="store_true", help="run a smoke retrieval")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    index = CorpusIndex(args.db)
    if args.reset:
        index.reset()

    try:
        documents = ingest_directory(args.corpus)
    except IngestionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    counts = index.add_documents(documents)
    stats = index.stats()

    if args.json:
        import json

        print(json.dumps({"added": counts, "stats": stats}, indent=2))
    else:
        print(f"corpus: {args.corpus}")
        print(f"added:  {counts['documents']} documents, {counts['sections']} sections, "
              f"{counts['chunks']} chunks")
        print(f"index:  {stats['db_path']} ({stats['size_bytes'] / 1024:.0f} KiB)")
        print(f"vocab:  {stats['vocabulary']} terms, avg chunk "
              f"{stats['avg_chunk_tokens']} tokens")

    if args.verify:
        probe = "hybrid retrieval with reciprocal rank fusion"
        result = RetrievalAgent(HybridRetriever(index)).retrieve(probe, k=3)
        if not result.hits:
            print("verification failed: no hits", file=sys.stderr)
            index.close()
            return 1
        print("\nverification probe:", probe)
        for hit in result.hits:
            print(f"  {hit.score:.3f}  {hit.title[:60]}  <{hit.section_label}>")

    index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
