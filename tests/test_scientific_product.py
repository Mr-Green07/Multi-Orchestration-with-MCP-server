"""Phase 5: CLI, HTTP API and end-to-end reproducibility.

The CLI and the API are tested by *running them*, not by importing their helpers:
a command that cannot be typed is not a command.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scientific_llm.api import ScientificAPI, make_handler, serve
from scientific_llm.index import CorpusIndex
from scientific_llm.ingest import ingest_directory

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "scientific_corpus"
BENCHMARK = ROOT / "data" / "benchmark" / "questions.json"
PYTHON = sys.executable


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("product") / "corpus.db"
    index = CorpusIndex(path)
    index.add_documents(ingest_directory(CORPUS))
    index.close()
    return path


# ------------------------------------------------------------------ CLI
def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PYTHON, "-m", "scientific_llm", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)


def test_cli_help_lists_every_command():
    result = run_cli("--help")
    assert result.returncode == 0
    for command in ("ingest", "stats", "search", "ask", "evaluate", "benchmark",
                    "trace", "serve", "demo", "clear"):
        assert command in result.stdout


def test_cli_without_a_command_prints_help():
    result = subprocess.run([PYTHON, "-m", "scientific_llm"], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 2
    assert "usage" in (result.stdout + result.stderr).lower()


def test_cli_ingest_stats_and_search(db, tmp_path):
    fresh = tmp_path / "fresh.db"
    ingest = run_cli("--db", str(fresh), "ingest", str(CORPUS))
    assert ingest.returncode == 0, ingest.stderr
    assert "ingested 10 document(s)" in ingest.stdout

    stats = run_cli("--db", str(fresh), "stats", "--json")
    payload = json.loads(stats.stdout)
    assert payload["documents"] == 10 and payload["chunks"] > 0

    search = run_cli("--db", str(fresh), "search", "hybrid retrieval fusion", "--k", "3",
                     "--json")
    result = json.loads(search.stdout)
    assert result["hits"] and result["rounds"] >= 1
    assert all("score" in hit for hit in result["hits"])


def test_cli_ask_returns_citations(db):
    result = run_cli("--db", str(db), "ask",
                     "How does citation validation reduce unsupported claims?", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["system"] == "multi_agent"
    assert payload["evidence"] and all(item["verified"] for item in payload["evidence"])
    assert payload["trace"]["agents"]
    assert payload["unsupported_sentences"] == []


def test_cli_ask_can_select_a_baseline(db):
    result = run_cli("--db", str(db), "ask", "what is reciprocal rank fusion?",
                     "--system", "conventional_rag", "--json")
    payload = json.loads(result.stdout)
    assert payload["system"] == "conventional_rag"
    assert "single dense retrieval pass" in " ".join(payload["notes"])


def test_cli_evaluate_and_benchmark(db, tmp_path):
    evaluate = run_cli("--db", str(db), "evaluate", "--systems", "single_agent",
                       "multi_agent", "--limit", "4", "--compare")
    assert evaluate.returncode == 0, evaluate.stderr
    assert "paired bootstrap" in evaluate.stdout
    assert "relevance" in evaluate.stdout

    report = tmp_path / "report.md"
    built = run_cli("--db", str(db), "benchmark", "--out", str(report))
    assert built.returncode == 0, built.stderr
    assert "Threats to validity" in report.read_text(encoding="utf-8")


def test_cli_trace_writes_a_file(db, tmp_path):
    out = tmp_path / "trace.json"
    result = run_cli("--db", str(db), "trace", "what is bm25?", "--out", str(out))
    assert result.returncode == 0, result.stderr
    trace = json.loads(out.read_text(encoding="utf-8"))
    assert trace["agents"] and trace["events"]


def test_cli_clear_then_stats(tmp_path):
    path = tmp_path / "clear.db"
    run_cli("--db", str(path), "ingest", str(CORPUS))
    assert run_cli("--db", str(path), "clear").returncode == 0
    payload = json.loads(run_cli("--db", str(path), "stats", "--json").stdout)
    assert payload["documents"] == 0


def test_cli_reports_a_missing_index_clearly(tmp_path):
    result = run_cli("--db", str(tmp_path / "missing.db"), "ask", "anything")
    assert result.returncode in {1, 2}
    assert "index is empty" in (result.stdout + result.stderr).lower()


def test_cli_test_helper_exposes_the_tokenizer():
    from scientific_llm.cli import _tokens

    assert _tokens("two words") == 2


# ------------------------------------------------------------------ API
@pytest.fixture(scope="module")
def live_server(db):
    index = CorpusIndex(db)
    server = serve(index, host="127.0.0.1", port=0, benchmark_path=str(BENCHMARK))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()
    index.close()


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_api_health_and_docs(live_server):
    status, payload = _get(f"{live_server}/health")
    assert status == 200 and payload["status"] == "ok"
    assert payload["index"]["documents"] == 10

    status, payload = _get(f"{live_server}/docs")
    assert status == 200
    assert "POST /ask" in payload["routes"]


def test_api_documents_and_single_document(live_server):
    status, payload = _get(f"{live_server}/documents")
    assert status == 200 and len(payload["documents"]) == 10
    doc_id = payload["documents"][0]["doc_id"]

    status, document = _get(f"{live_server}/documents/{doc_id}")
    assert status == 200
    assert document["sections"] and document["metadata"]["title"]

    status, missing = _get(f"{live_server}/documents/nope")
    assert status == 404 and "error" in missing


def test_api_search(live_server):
    status, payload = _post(f"{live_server}/search",
                            {"query": "reciprocal rank fusion", "k": 3})
    assert status == 200
    assert len(payload["hits"]) <= 3
    assert payload["expanded_terms"] is not None


def test_api_ask_returns_evidence_and_a_trace(live_server):
    status, payload = _post(f"{live_server}/ask",
                            {"question": "How does hybrid retrieval compare to BM25?"})
    assert status == 200
    assert payload["evidence"]
    assert payload["citations"] == [item["evidence_id"] for item in payload["evidence"]]
    trace_id = payload["trace"]["trace_id"]

    status, trace = _get(f"{live_server}/trace/{trace_id}")
    assert status == 200 and trace["events"]
    assert _get(f"{live_server}/trace/unknown")[0] == 404


def test_api_validation_errors(live_server):
    assert _post(f"{live_server}/ask", {})[0] == 400
    assert _post(f"{live_server}/search", {})[0] == 400
    assert _get(f"{live_server}/ask")[0] == 405
    assert _get(f"{live_server}/nope")[0] == 404


def test_api_evaluate_with_limited_systems(live_server):
    status, payload = _post(f"{live_server}/evaluate",
                            {"systems": ["multi_agent"], "limit": 3})
    assert status == 200
    assert "multi_agent" in payload["summary"]
    assert _post(f"{live_server}/evaluate", {"systems": ["nope"]})[0] == 400


def test_api_handles_malformed_json(live_server):
    request = urllib.request.Request(
        f"{live_server}/ask", data=b"{not json",
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 400


def test_api_application_object_can_be_used_directly(db):
    index = CorpusIndex(db)
    app = ScientificAPI(index)
    status, payload = app.handle("GET", "/stats", {}, {})
    assert status == 200 and payload["documents"] == 10
    status, payload = app.handle("POST", "/search", {}, {"query": "reranking", "k": 2})
    assert status == 200 and payload["hits"]
    handler = make_handler(app)
    assert handler.server_version.startswith("ScientificLLM")
    index.close()


# ------------------------------------------------------------------ end to end
def test_end_to_end_pipeline_from_scratch(tmp_path):
    """ingest -> chunk -> index -> retrieve -> answer -> validate -> judge."""
    from scientific_llm.agents import CoordinatorAgent
    from scientific_llm.judge import Judge
    from scientific_llm.retrieval import HybridRetriever, RetrievalAgent

    index = CorpusIndex(tmp_path / "e2e.db")
    counts = index.add_documents(ingest_directory(CORPUS))
    assert counts == {"documents": 10, "sections": 80, "chunks": 80}

    result = RetrievalAgent(HybridRetriever(index)).retrieve(
        "How many candidates does the cascade keep before reranking?", k=5)
    assert result.hits
    assert any("forty" in hit.text.lower() for hit in result.hits)

    bundle = CoordinatorAgent(index).answer(
        "How many candidates does the cascade keep before reranking?")
    assert "[E1]" in bundle.answer
    assert all(item.verified for item in bundle.evidence)

    judgement = Judge(index).assess(bundle)
    assert judgement.citation_support == 1.0
    assert judgement.hallucination_rate == 0.0
    index.close()


def test_reproducibility_across_two_independent_builds(tmp_path):
    """Two fresh builds of the same corpus must answer identically."""
    from scientific_llm.agents import CoordinatorAgent

    answers = []
    for name in ("first.db", "second.db"):
        index = CorpusIndex(tmp_path / name)
        index.add_documents(ingest_directory(CORPUS))
        bundle = CoordinatorAgent(index).answer("what is reciprocal rank fusion?")
        answers.append((bundle.answer, [item.chunk_id for item in bundle.evidence],
                        index.stats()["vocabulary"]))
        index.close()
    assert answers[0] == answers[1]


def test_scripts_are_executable_and_documented():
    for script in ("build_corpus.py", "run_benchmark.py", "make_sample_pdf.py",
                   "reproduce.sh"):
        path = ROOT / "scripts" / script
        assert path.exists(), script
        text = path.read_text(encoding="utf-8")
        assert text.startswith("#!"), f"{script} needs a shebang"
        assert len(text.splitlines()) > 10


def test_docs_cover_every_phase():
    doc = (ROOT / "SCIENTIFIC_LLM.md").read_text(encoding="utf-8")
    for phrase in ("Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5",
                   "python -m scientific_llm ingest", "scientific_llm evaluate",
                   "reproduce.sh", "Not wired into the MCP server"):
        assert phrase in doc, phrase
