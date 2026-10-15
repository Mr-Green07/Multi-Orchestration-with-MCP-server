"""
Metrics harness (spec section 14).

Runs a battery of scenarios through the agent with a scripted model and computes:
  * valid JSON rate
  * correct tool-selection rate
  * correct argument rate
  * tool execution success rate
  * final-answer correctness
  * average number of steps
  * average latency
  * failure rate

GPU memory use is reported as N/A here because these runs use a scripted model
(no GPU). With the real model, model_loader.report_memory() supplies live GPU
numbers -- see the README > Benchmarking note.

Run with:  pytest -s tests/test_metrics.py   (the -s flag shows the summary)
"""

import time

import security
from agent_controller import AgentController, extract_json, validate_action
from tools import ToolContext
from conftest import ScriptedModel, FakeRetriever


def _agent(responses, ctx):
    return AgentController(ScriptedModel(responses), ctx,
                           logger=security.get_logger("metrics"), max_steps=4)


def test_agent_metrics(sample_db, ws_subdir, capsys):
    name, path = ws_subdir
    (path / "a.txt").write_text("hello", encoding="utf-8")
    report_name = "_pytest_metrics_report.md"
    report_path = security.WORKSPACE_DIR / report_name

    ctx = ToolContext(confirm=lambda _m: True, db_path=sample_db, retriever=FakeRetriever())

    scenarios = [
        {
            "name": "no_tool",
            "request": "Say hello.",
            "responses": ['{"action": "final", "answer": "Hello!"}'],
            "expected_tool": None,
            "arg_ok": lambda calls: True,
            "answer_ok": lambda a: "hello" in a.lower(),
            "expect_success": True,
        },
        {
            "name": "calculate",
            "request": "What is 6 times 7?",
            "responses": [
                '{"action": "tool", "tool": "calculate", "arguments": {"expression": "6 * 7"}}',
                '{"action": "final", "answer": "6 times 7 is 42."}',
            ],
            "expected_tool": "calculate",
            "arg_ok": lambda calls: calls[0]["arguments"].get("expression") == "6 * 7",
            "answer_ok": lambda a: "42" in a,
            "expect_success": True,
        },
        {
            "name": "file_listing",
            "request": "List the files.",
            "responses": [
                f'{{"action": "tool", "tool": "list_files", "arguments": {{"subdir": "{name}"}}}}',
                '{"action": "final", "answer": "Found a.txt."}',
            ],
            "expected_tool": "list_files",
            "arg_ok": lambda calls: calls[0]["arguments"].get("subdir") == name,
            "answer_ok": lambda a: "a.txt" in a,
            "expect_success": True,
        },
        {
            "name": "document_search",
            "request": "Capital of France from docs?",
            "responses": [
                '{"action": "tool", "tool": "search_documents", "arguments": {"query": "capital of France"}}',
                '{"action": "final", "answer": "It is Paris (guide.txt)."}',
            ],
            "expected_tool": "search_documents",
            "arg_ok": lambda calls: "France" in calls[0]["arguments"].get("query", ""),
            "answer_ok": lambda a: "Paris" in a,
            "expect_success": True,
        },
        {
            "name": "sqlite",
            "request": "How many users?",
            "responses": [
                '{"action": "tool", "tool": "query_sqlite", "arguments": {"query": "SELECT COUNT(*) AS n FROM users"}}',
                '{"action": "final", "answer": "There are 3 users."}',
            ],
            "expected_tool": "query_sqlite",
            "arg_ok": lambda calls: "count" in calls[0]["arguments"].get("query", "").lower(),
            "answer_ok": lambda a: "3" in a,
            "expect_success": True,
        },
        {
            "name": "report",
            "request": "Write a report.",
            "responses": [
                f'{{"action": "tool", "tool": "create_report", "arguments": {{"filename": "{report_name}", "title": "R", "content": "Body"}}}}',
                '{"action": "final", "answer": "Saved the report."}',
            ],
            "expected_tool": "create_report",
            "arg_ok": lambda calls: calls[0]["arguments"].get("filename") == report_name,
            "answer_ok": lambda a: "report" in a.lower() or "saved" in a.lower(),
            "expect_success": True,
        },
        {
            "name": "unknown_tool",
            "request": "Use a made-up tool.",
            "responses": [
                '{"action": "tool", "tool": "does_not_exist", "arguments": {}}',
                '{"action": "final", "answer": "That tool is not available."}',
            ],
            "expected_tool": "does_not_exist",   # selection recorded, execution must fail
            "arg_ok": lambda calls: True,
            "answer_ok": lambda a: "not available" in a.lower(),
            "expect_success": False,
        },
    ]

    total = len(scenarios)
    valid_json_outputs = 0
    total_model_outputs = 0
    correct_tool = 0
    correct_args = 0
    correct_answer = 0
    steps_sum = 0
    latency_sum = 0.0
    failures = 0
    tool_exec_attempts = 0
    tool_exec_success = 0

    try:
        for sc in scenarios:
            agent = _agent(sc["responses"], ctx)
            t0 = time.time()
            res = agent.run(sc["request"])
            latency_sum += time.time() - t0
            steps_sum += res.steps

            # valid JSON rate over every raw model output produced
            for entry in res.trace:
                if entry["type"] == "model_raw":
                    total_model_outputs += 1
                    obj, err = extract_json(entry["content"])
                    if obj is not None:
                        kind, _p, verr = validate_action(obj)
                        if kind is not None:
                            valid_json_outputs += 1

            # tool selection
            first_tool = res.tool_calls[0]["tool"] if res.tool_calls else None
            if first_tool == sc["expected_tool"]:
                correct_tool += 1

            # argument correctness
            if res.tool_calls and sc["arg_ok"](res.tool_calls):
                correct_args += 1
            elif not res.tool_calls and sc["expected_tool"] is None:
                correct_args += 1

            # tool execution success (only where success is expected)
            for call in res.tool_calls:
                if sc["expect_success"]:
                    tool_exec_attempts += 1
                    if call["result"].get("ok"):
                        tool_exec_success += 1

            # answer correctness
            if sc["answer_ok"](res.answer):
                correct_answer += 1

            # failure rate
            if res.error is not None or res.exhausted:
                failures += 1
    finally:
        report_path.unlink(missing_ok=True)

    metrics = {
        "valid_json_rate": valid_json_outputs / max(total_model_outputs, 1),
        "correct_tool_selection_rate": correct_tool / total,
        "correct_argument_rate": correct_args / total,
        "tool_execution_success_rate": tool_exec_success / max(tool_exec_attempts, 1),
        "final_answer_correctness": correct_answer / total,
        "avg_steps": steps_sum / total,
        "avg_latency_s": latency_sum / total,
        "failure_rate": failures / total,
        "gpu_memory_use": "N/A (scripted model; use model_loader.report_memory() with the real model)",
    }

    with capsys.disabled():
        print("\n================ AGENT METRICS ================")
        for k, v in metrics.items():
            print(f"  {k:32s}: {v:.3f}" if isinstance(v, float) else f"  {k:32s}: {v}")
        print("===============================================")

    # Sanity thresholds for the scripted battery.
    assert metrics["valid_json_rate"] == 1.0
    assert metrics["correct_tool_selection_rate"] == 1.0
    assert metrics["correct_argument_rate"] == 1.0
    assert metrics["tool_execution_success_rate"] == 1.0
    assert metrics["final_answer_correctness"] == 1.0
    assert metrics["failure_rate"] == 0.0
