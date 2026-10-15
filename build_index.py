"""
build_index.py
==============
Build a local FAISS document index from files in ``documents/`` (or any dir).

Examples
--------
    # Index everything in documents/ into indexes/default
    python build_index.py

    # Custom locations + chunking, explicit local embedding model
    python build_index.py --documents-dir documents \
                          --index-dir indexes/default \
                          --embed-model models/all-MiniLM-L6-v2 \
                          --chunk-size 800 --overlap 120

Supported inputs: .pdf, .txt, .md/.markdown, .docx
"""

from __future__ import annotations

import argparse
import sys

import security
import retrieval


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Build a local document index for the offline agent.")
    p.add_argument("--documents-dir", default=str(security.DOCUMENTS_DIR))
    p.add_argument("--index-dir", default=str(security.INDEXES_DIR / "default"))
    p.add_argument("--embed-model", default=retrieval.DEFAULT_EMBED_MODEL,
                   help="Local sentence-transformers directory or (cached) model name.")
    p.add_argument("--chunk-size", type=int, default=800)
    p.add_argument("--overlap", type=int, default=120)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    print(f"Documents : {args.documents_dir}")
    print(f"Index dir : {args.index_dir}")
    print(f"Embeddings: {args.embed_model}")
    print("Building index (this loads the embedding model locally)...")

    retriever = retrieval.Retriever(index_dir=args.index_dir, embed_model=args.embed_model)
    try:
        stats = retriever.build(args.documents_dir, chunk_size=args.chunk_size, overlap=args.overlap)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR while building index: {exc}")
        return 1

    retriever.save()
    print(f"\nDone. Indexed {stats['documents']} document(s) into {stats['chunks']} chunk(s).")
    if stats.get("skipped"):
        print("Skipped:")
        for name, why in stats["skipped"]:
            print(f"  - {name}: {why}")
    print(f"Saved to: {args.index_dir}")
    print("Load it in the agent with:  /index " + args.index_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
