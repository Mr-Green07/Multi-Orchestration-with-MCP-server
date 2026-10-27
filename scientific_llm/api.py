"""scientific_llm/api.py
======================
A JSON HTTP API over the corpus, the retrieval stack and the agent pipeline.

Deliberately built on ``http.server`` rather than FastAPI: the project's promise is
"offline, no heavyweight dependencies", and an evaluator should be able to run the
API on a clean machine with nothing but the standard library. The surface is small:

===========================  ==================================================
GET  /health                 liveness, index stats
GET  /stats                  corpus statistics
GET  /documents              document metadata (no raw text)
GET  /documents/{doc_id}     one document: metadata + sections
POST /search  {query,k}      hybrid retrieval with per-stage scores
POST /ask     {question}     multi-agent answer (answer, evidence, trace)
POST /evaluate {systems}     run the benchmark against named systems
GET  /trace/{trace_id}       a stored trace from the last answer
GET  /docs                   this table, as JSON
===========================  ==================================================
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from scientific_llm.agents import CoordinatorAgent
from scientific_llm.baselines import ConventionalRAGSystem, SingleAgentSystem
from scientific_llm.evaluation import BenchmarkDataset, EvaluationRunner, resolve_dataset
from scientific_llm.index import CorpusIndex
from scientific_llm.retrieval import HybridRetriever, RetrievalAgent
from scientific_llm.text import tokenize

ROUTES = {
    "GET /health": "liveness plus index statistics",
    "GET /stats": "corpus statistics (documents, sections, chunks, vocabulary)",
    "GET /documents": "list document metadata",
    "GET /documents/{doc_id}": "one document with its sections",
    "POST /search": "hybrid retrieval; body {query, k}",
    "POST /ask": "multi-agent answer; body {question}",
    "POST /evaluate": "benchmark run; body {systems: [...], limit: n}",
    "GET /trace/{trace_id}": "trace of a recent answer",
    "GET /docs": "this route table",
}


class ScientificAPI:
    """Application object; the HTTP handler is a thin shell over it."""

    def __init__(self, index: CorpusIndex, *, benchmark_path: str | None = None) -> None:
        self.index = index
        self.retriever = RetrievalAgent(HybridRetriever(index))
        self.coordinator = CoordinatorAgent(index)
        self.benchmark_path = benchmark_path
        self.traces: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._systems = {
            "conventional_rag": lambda: ConventionalRAGSystem(index),
            "single_agent": lambda: SingleAgentSystem(index),
            "multi_agent": lambda: CoordinatorAgent(index),
        }

    # ------------------------------------------------------------------ handlers
    def handle(self, method: str, path: str, query: dict[str, list[str]],
               body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/docs":
            return 200, {"routes": ROUTES}
        if path == "/health":
            return 200, {"status": "ok", "index": self.index.stats()}
        if path == "/stats":
            return 200, self.index.stats()
        if path == "/documents":
            return 200, {"documents": [
                {"doc_id": doc_id, "title": meta.title, "year": meta.year,
                 "authors": meta.authors, "venue": meta.venue, "doi": meta.doi}
                for doc_id, meta in self.index.metadata().items()]}
        if path.startswith("/documents/"):
            doc_id = path[len("/documents/"):]
            document = self.index.document(doc_id)
            if document is None:
                return 404, {"error": f"no document '{doc_id}'"}
            return 200, {
                "doc_id": document.doc_id,
                "metadata": document.metadata.model_dump(),
                "sections": [{"heading": section.heading, "label": section.label,
                              "tokens": len(tokenize(section.text, keep_stopwords=True))}
                             for section in document.sections],
            }
        if path == "/search":
            if method != "POST":
                return 405, {"error": "use POST"}
            question = str(body.get("query") or query.get("query", [""])[0]).strip()
            if not question:
                return 400, {"error": "body must contain 'query'"}
            k = int(body.get("k") or 8)
            result = self.retriever.retrieve(question, k=k)
            return 200, result.as_dict()
        if path == "/ask":
            if method != "POST":
                return 405, {"error": "use POST"}
            question = str(body.get("question") or query.get("question", [""])[0]).strip()
            if not question:
                return 400, {"error": "body must contain 'question'"}
            bundle = self.coordinator.answer(question)
            payload = bundle.model_dump()
            payload["citations"] = bundle.citations()
            trace = bundle.trace or {}
            if trace.get("trace_id"):
                with self._lock:
                    self.traces[str(trace["trace_id"])] = trace
            return 200, payload
        if path == "/evaluate":
            if method != "POST":
                return 405, {"error": "use POST"}
            names = body.get("systems") or ["conventional_rag", "single_agent", "multi_agent"]
            unknown = [name for name in names if name not in self._systems]
            if unknown:
                return 400, {"error": f"unknown systems: {', '.join(unknown)}",
                             "available": sorted(self._systems)}
            dataset = resolve_dataset(
                BenchmarkDataset.load(self.benchmark_path), self.index)
            runner = EvaluationRunner(dataset, index=self.index)
            runner.run_all({name: self._systems[name]() for name in names},
                           limit=body.get("limit"))
            return 200, {"summary": runner.summary()}
        if path.startswith("/trace/"):
            trace_id = path[len("/trace/"):]
            stored = self.traces.get(trace_id)
            if stored is None:
                return 404, {"error": f"unknown trace '{trace_id}'"}
            return 200, stored
        return 404, {"error": f"no route for {method} {path}", "routes": ROUTES}


def make_handler(app: ScientificAPI) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ScientificLLM/1.0"

        def _respond(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(encoded)

        def do_OPTIONS(self) -> None:              # noqa: N802 - stdlib naming
            self._respond(200, {"ok": True})

        def do_GET(self) -> None:                  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:                 # noqa: N802
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            parsed = urlparse(self.path)
            body: dict[str, Any] = {}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._respond(400, {"error": "body must be JSON"})
                    return
            try:
                status, payload = app.handle(method, parsed.path,
                                             parse_qs(parsed.query), body)
            except Exception as exc:               # never leak a traceback
                status, payload = 500, {"error": f"{type(exc).__name__}: {exc}"}
            self._respond(status, payload)

        def log_message(self, fmt: str, *args: Any) -> None:
            if app.index is not None:
                pass                               # quiet by default

    return Handler


def serve(index: CorpusIndex, host: str = "0.0.0.0", port: int = 8017,
          benchmark_path: str | None = None) -> ThreadingHTTPServer:
    app = ScientificAPI(index, benchmark_path=benchmark_path)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    return server


def main(argv: list[str] | None = None) -> int:
    import argparse

    from scientific_llm.index import DEFAULT_DB_PATH

    parser = argparse.ArgumentParser(prog="scientific_llm.api",
                                     description="JSON API for the scientific RAG stack")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument("--benchmark", default=None)
    args = parser.parse_args(argv)

    index = CorpusIndex(args.db)
    stats = index.stats()
    if not stats["documents"]:
        print("! the index is empty: run `python -m scientific_llm ingest data/scientific_corpus`")
    server = serve(index, host=args.host, port=args.port,
                   benchmark_path=args.benchmark)
    print(f"scientific_llm api listening on http://{args.host}:{args.port} "
          f"({stats['documents']} documents, {stats['chunks']} chunks)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
        index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
