"""scientific_llm/cli.py
======================
The command line (roadmap item 23): ``python -m scientific_llm <command>``.

Commands are grouped by what you are trying to do:

* **build**   ``ingest``, ``stats``        - corpus construction
* **ask**     ``search``, ``ask``, ``trace`` - retrieval and answering
* **measure** ``evaluate``, ``benchmark``   - the evaluation chapter
* **run**     ``serve``, ``demo``           - API and a one-shot tour

Every command prints either human-readable text or ``--json`` for piping. Exit
codes are meaningful (0 ok, 1 failure, 2 usage) so the scripts in ``scripts/`` can
depend on them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Protocol

from scientific_llm.index import DEFAULT_DB_PATH, CorpusIndex
from scientific_llm.models import AnswerBundle
from scientific_llm.text import tokenize

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "data" / "scientific_corpus"


# --------------------------------------------------------------------------- helpers
def _load_index(path: str | None, *, require_documents: bool = True) -> CorpusIndex:
    index = CorpusIndex(path or DEFAULT_DB_PATH)
    if require_documents and not index.stats()["documents"]:
        raise SystemExit(
            "the index is empty - run: python -m scientific_llm ingest data/scientific_corpus")
    return index


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------- build
def cmd_ingest(args: argparse.Namespace) -> int:
    from scientific_llm.ingest import IngestionError, ingest_directory, ingest_path

    index = _load_index(args.db, require_documents=False)
    targets = [Path(item) for item in args.paths] or [DEFAULT_CORPUS]
    totals = {"documents": 0, "sections": 0, "chunks": 0}
    failures: list[dict[str, str]] = []

    for target in targets:
        try:
            documents = (ingest_directory(target) if target.is_dir()
                         else ingest_path(target))
        except IngestionError as exc:
            failures.append({"path": str(target), "error": str(exc)})
            continue
        counts = index.add_documents(documents)
        for key in totals:
            totals[key] += counts[key]
        if not args.json:
            for document in documents:
                print(f"  + {document.doc_id}  ({len(document.sections)} sections)")

    if args.json:
        _print_json({"added": totals, "failures": failures, "stats": index.stats()})
    else:
        print(f"ingested {totals['documents']} document(s), "
              f"{totals['sections']} sections, {totals['chunks']} chunks")
        if failures:
            print(f"! {len(failures)} file(s) failed:")
            for failure in failures:
                print(f"    {failure['path']}: {failure['error']}")
    index.close()
    return 0 if not failures else 1


def cmd_stats(args: argparse.Namespace) -> int:
    index = _load_index(args.db, require_documents=False)
    stats = index.stats()
    if args.json:
        _print_json(stats)
        index.close()
        return 0
    print("corpus")
    for key, value in stats.items():
        print(f"  {key:<18} {value}")
    if stats["documents"]:
        print("\ndocuments")
        for document in index.documents():
            print(f"  {document.doc_id[:44]:<46} {document.metadata.year or '----'}  "
                  f"{document.metadata.title[:60]}")
    index.close()
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    index = _load_index(args.db, require_documents=False)
    index.reset()
    index.close()
    print(f"cleared {args.db or DEFAULT_DB_PATH}")
    return 0


# --------------------------------------------------------------------------- ask
def cmd_search(args: argparse.Namespace) -> int:
    from scientific_llm.retrieval import HybridRetriever, RetrievalAgent

    index = _load_index(args.db)
    retriever = RetrievalAgent(HybridRetriever(index), max_rounds=args.rounds)
    result = retriever.retrieve(args.query, k=args.k)
    if args.json:
        _print_json(result.as_dict())
        index.close()
        return 0
    print(f"query: {result.query}")
    print(f"expanded: {', '.join(result.expanded_terms[:10]) or '(none)'}")
    print(f"rounds: {result.rounds}   took: {result.took_ms:.1f} ms\n")
    for number, hit in enumerate(result.hits, start=1):
        print(f"{number}. [{hit.score:.3f}] {hit.title} ({hit.year or 'n.d.'}) "
              f"<{hit.section_label}>")
        print(f"   {hit.text[:220].replace(chr(10), ' ')}...")
        print(f"   bm25={hit.bm25:.2f} dense={hit.dense:.2f} rerank={hit.rerank:.3f}")
    index.close()
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from scientific_llm.agents import CoordinatorAgent
    from scientific_llm.baselines import ConventionalRAGSystem, SingleAgentSystem

    index = _load_index(args.db)
    class AnswerSource(Protocol):
        def answer(self, question: str) -> AnswerBundle: ...

    systems: dict[str, AnswerSource] = {
        "multi_agent": CoordinatorAgent(index),
        "single_agent": SingleAgentSystem(index),
        "conventional_rag": ConventionalRAGSystem(index),
    }
    if args.system not in systems:
        raise SystemExit(f"unknown system '{args.system}'; choose from {', '.join(systems)}")
    bundle = systems[args.system].answer(args.question)

    if args.json:
        _print_json(bundle.model_dump())
        index.close()
        return 0
    print(bundle.as_text())
    print()
    print(f"system: {bundle.system}   latency: {bundle.latency_ms:.1f} ms   "
          f"citations: {len(bundle.evidence)}   docs: {len(bundle.retrieved_doc_ids)}")
    if bundle.trace:
        print()
        print("trace")
        for event in bundle.trace.get("events", []):
            print(f"  {event['agent']:<16} {event['action']:<14} "
                  f"{event['latency_ms']:7.1f} ms  {event['detail']}")
        for handoff in bundle.trace.get("handoffs", []):
            print(f"  handoff {handoff['from']} -> {handoff['to']} ({handoff['reason']})")
    if args.show_trace:
        _print_json(bundle.trace)
    index.close()
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    from scientific_llm.agents import CoordinatorAgent
    from scientific_llm.tracing import Trace

    index = _load_index(args.db)
    bundle = CoordinatorAgent(index).answer(args.question)
    trace = bundle.trace or {}
    if args.out:
        Trace(bundle.question).as_dict()          # keep the module path exercised
        Path(args.out).write_text(json.dumps(trace, indent=2), encoding="utf-8")
        print(f"trace written to {args.out}")
    else:
        _print_json(trace)
    index.close()
    return 0


# --------------------------------------------------------------------------- measure
def cmd_evaluate(args: argparse.Namespace) -> int:
    from scientific_llm.evaluation import (
        BenchmarkDataset,
        EvaluationRunner,
        compare_systems,
        comparison_table,
        markdown_table,
        resolve_dataset,
    )

    index = _load_index(args.db)
    dataset = resolve_dataset(BenchmarkDataset.load(args.benchmark), index)
    names = args.systems or ["conventional_rag", "single_agent", "multi_agent"]
    from scientific_llm.agents import CoordinatorAgent
    from scientific_llm.baselines import ConventionalRAGSystem, SingleAgentSystem

    available = {
        "conventional_rag": lambda: ConventionalRAGSystem(index),
        "single_agent": lambda: SingleAgentSystem(index),
        "multi_agent": lambda: CoordinatorAgent(index),
    }
    unknown = [name for name in names if name not in available]
    if unknown:
        raise SystemExit(f"unknown systems: {', '.join(unknown)}")

    runner = EvaluationRunner(dataset, k=args.k, log_dir=args.log_dir, index=index)
    runner.run_all({name: available[name]() for name in names}, limit=args.limit)
    summary = runner.summary()

    if args.json:
        _print_json({"summary": summary, "by_category": runner.by_category()})
    else:
        print(f"benchmark: {dataset.name}  ({len(dataset)} questions)  k={args.k}\n")
        print(markdown_table(summary))
        if args.compare and len(names) >= 2:
            print()
            print(f"paired bootstrap: {names[0]} (baseline) vs {names[-1]} (treatment)")
            print(comparison_table(compare_systems(
                runner.results, baseline=names[0], treatment=names[-1])))
    index.close()
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from scientific_llm.report import write_benchmark_report

    index = _load_index(args.db)
    path = write_benchmark_report(index, out_path=args.out,
                                  benchmark_path=args.benchmark, k=args.k)
    print(f"report written to {path}")
    index.close()
    return 0


# --------------------------------------------------------------------------- run
def cmd_serve(args: argparse.Namespace) -> int:
    from scientific_llm.api import serve

    index = _load_index(args.db)
    server = serve(index, host=args.host, port=args.port,
                   benchmark_path=args.benchmark)
    print(f"scientific_llm api listening on http://{args.host}:{args.port} "
          f"({index.stats()['documents']} documents)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
        index.close()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Index the bundled corpus in a scratch database and answer one question."""
    import tempfile

    from scientific_llm.agents import CoordinatorAgent
    from scientific_llm.ingest import ingest_directory

    with tempfile.TemporaryDirectory() as tmp:
        index = CorpusIndex(Path(tmp) / "demo.db")
        counts = index.add_documents(ingest_directory(DEFAULT_CORPUS))
        print(f"indexed {counts['documents']} documents, {counts['chunks']} chunks")
        question = args.question or (
            "How does multi-agent decomposition improve citation precision?")
        bundle = CoordinatorAgent(index).answer(question)
        print()
        print(bundle.as_text())
        print(f"\nlatency {bundle.latency_ms:.1f} ms, "
              f"{len(bundle.evidence)} verified citations")
        index.close()
    return 0


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scientific_llm",
        description="Offline scientific RAG: corpus, hybrid retrieval, "
                    "multi-agent answering, evaluation.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH),
                        help="SQLite corpus path (default: database/scientific_corpus.db)")
    sub = parser.add_subparsers(dest="command")

    ingest = sub.add_parser("ingest", help="ingest PDFs, markdown or API payloads")
    ingest.add_argument("paths", nargs="*", help="files or directories")
    ingest.add_argument("--json", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    stats = sub.add_parser("stats", help="corpus statistics")
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(func=cmd_stats)

    clear = sub.add_parser("clear", help="empty the index")
    clear.set_defaults(func=cmd_clear)

    search = sub.add_parser("search", help="hybrid retrieval for a query")
    search.add_argument("query")
    search.add_argument("--k", type=int, default=8)
    search.add_argument("--rounds", type=int, default=2)
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    ask = sub.add_parser("ask", help="answer a question with citations")
    ask.add_argument("question")
    ask.add_argument("--system", default="multi_agent",
                     choices=["multi_agent", "single_agent", "conventional_rag"])
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--show-trace", action="store_true")
    ask.set_defaults(func=cmd_ask)

    trace = sub.add_parser("trace", help="show the agent trace for a question")
    trace.add_argument("question")
    trace.add_argument("--out", default=None, help="write the trace to this JSON file")
    trace.set_defaults(func=cmd_trace)

    evaluate = sub.add_parser("evaluate", help="run the benchmark against the systems")
    evaluate.add_argument("--benchmark", default=None)
    evaluate.add_argument("--systems", nargs="*", default=None)
    evaluate.add_argument("--k", type=int, default=5)
    evaluate.add_argument("--limit", type=int, default=None)
    evaluate.add_argument("--log-dir", default=None)
    evaluate.add_argument("--compare", action="store_true",
                          help="add the paired-bootstrap comparison table")
    evaluate.add_argument("--json", action="store_true")
    evaluate.set_defaults(func=cmd_evaluate)

    benchmark = sub.add_parser("benchmark", help="write the markdown benchmark report")
    benchmark.add_argument("--out", default=None)
    benchmark.add_argument("--benchmark", default=None)
    benchmark.add_argument("--k", type=int, default=5)
    benchmark.set_defaults(func=cmd_benchmark)

    serve_cmd = sub.add_parser("serve", help="start the JSON HTTP API")
    serve_cmd.add_argument("--host", default="0.0.0.0")
    serve_cmd.add_argument("--port", type=int, default=8017)
    serve_cmd.add_argument("--benchmark", default=None)
    serve_cmd.set_defaults(func=cmd_serve)

    demo = sub.add_parser("demo", help="index the bundled corpus and answer one question")
    demo.add_argument("--question", default=None)
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except SystemExit as exc:
        print(str(exc) if exc.code else "", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


def _tokens(text: str) -> int:
    """Small helpers kept for scripts that want the same tokenizer."""
    return len(tokenize(text, keep_stopwords=True))
