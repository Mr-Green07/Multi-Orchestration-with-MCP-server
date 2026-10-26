"""
End-to-end tests for the agent loop using a scripted fake model.

Covers the 10 required scenarios plus max-step enforcement, invalid-output
recovery and tool-failure recovery. Because the model is scripted, these run
fully offline with no torch/transformers required.
"""

import security as security
import tools as tools
from agent_controller import AgentController
from tests.conftest import FakeRetriever, ScriptedModel
from tools import ToolContext


def make_agent(responses, ctx=None, max_steps=security.MAX_STEPS):
    ctx = ctx or ToolContext(confirm=lambda _m: True)
    model = ScriptedModel(responses)
    agent = AgentController(generate_fn=model, ctx=ctx,
                            logger=security.get_logger("test"), max_steps=max_steps)
    return agent, model


# --------------------------- 1. no tool needed ---------------------------
def test_e2e_no_tool():
    agent, _ = make_agent(['{"action": "final", "answer": "Hello there!"}'])
    res = agent.run("Say hi")
    assert res.answer == "Hello there!"
    assert res.steps == 1
    assert res.tool_calls == []


# --------------------------- 2. calculation ---------------------------
def test_e2e_calculation():
    agent, _ = make_agent([
        '{"action": "tool", "tool": "calculate", "arguments": {"expression": "25 * 4"}}',
        '{"action": "final", "answer": "25 multiplied by 4 equals 100."}',
    ])
    res = agent.run("Calculate 25 multiplied by 4.")
    assert "100" in res.answer
    assert res.tool_calls[0]["tool"] == "calculate"
    assert res.tool_calls[0]["result"]["result"]["value"] == 100


# --------------------------- 3. file listing ---------------------------
def test_e2e_file_listing(ws_subdir):
    name, path = ws_subdir
    (path / "a.txt").write_text("x", encoding="utf-8")
    agent, _ = make_agent([
        f'{{"action": "tool", "tool": "list_files", "arguments": {{"subdir": "{name}"}}}}',
        '{"action": "final", "answer": "There is 1 file: a.txt"}',
    ])
    res = agent.run("What files are in that folder?")
    assert res.tool_calls[0]["tool"] == "list_files"
    assert res.tool_calls[0]["result"]["ok"] is True


# --------------------------- 4. document search ---------------------------
def test_e2e_document_search():
    ctx = ToolContext(confirm=lambda _m: True, retriever=FakeRetriever())
    agent, _ = make_agent([
        '{"action": "tool", "tool": "search_documents", "arguments": {"query": "capital of France"}}',
        '{"action": "final", "answer": "According to guide.txt, the capital of France is Paris."}',
    ], ctx=ctx)
    res = agent.run("What is the capital of France per the docs?")
    assert res.tool_calls[0]["tool"] == "search_documents"
    assert "Paris" in res.answer


# --------------------------- 5. sqlite query ---------------------------
def test_e2e_sqlite(ctx):
    agent, _ = make_agent([
        '{"action": "tool", "tool": "query_sqlite", "arguments": {"query": "SELECT COUNT(*) AS n FROM users"}}',
        '{"action": "final", "answer": "There are 3 users."}',
    ], ctx=ctx)
    res = agent.run("How many users are there?")
    assert res.tool_calls[0]["result"]["ok"] is True
    assert "3" in res.answer


# --------------------------- 6. report generation ---------------------------
def test_e2e_report():
    fname = "pytest_e2e_report.md"
    target = security.WORKSPACE_DIR / fname
    try:
        agent, _ = make_agent([
            f'{{"action": "tool", "tool": "create_report", "arguments": {{"filename": "{fname}", "title": "Summary", "content": "All good."}}}}',
            '{"action": "final", "answer": "Report saved."}',
        ])
        res = agent.run("Create a summary report.")
        assert res.tool_calls[0]["result"]["ok"] is True
        assert target.exists()
    finally:
        target.unlink(missing_ok=True)


# --------------------------- 7. invalid path ---------------------------
def test_e2e_invalid_path():
    agent, _ = make_agent([
        '{"action": "tool", "tool": "read_text_file", "arguments": {"path": "../../etc/passwd"}}',
        '{"action": "final", "answer": "I could not read that file: the path is outside the workspace."}',
    ])
    res = agent.run("Read /etc/passwd")
    assert res.tool_calls[0]["result"]["ok"] is False
    assert "workspace" in res.answer.lower()


# --------------------------- 8. unavailable internet ---------------------------
def test_e2e_internet_unavailable():
    agent, _ = make_agent([
        '{"action": "final", "answer": "I cannot access the internet; I run fully offline."}',
    ])
    res = agent.run("Fetch today's news from the web.")
    assert res.tool_calls == []
    assert "offline" in res.answer.lower() or "internet" in res.answer.lower()


# --------------------------- 9. unknown tool ---------------------------
def test_e2e_unknown_tool():
    agent, _ = make_agent([
        '{"action": "tool", "tool": "delete_everything", "arguments": {}}',
        '{"action": "final", "answer": "That tool is not available."}',
    ])
    res = agent.run("Delete all my files")
    assert res.tool_calls[0]["result"]["ok"] is False
    assert "Unknown tool" in res.tool_calls[0]["result"]["error"]


# --------------------------- 10. malicious shell command ---------------------------
def test_e2e_malicious_shell():
    agent, _ = make_agent([
        '{"action": "tool", "tool": "calculate", "arguments": {"expression": "__import__(\'os\').system(\'rm -rf /\')"}}',
        '{"action": "final", "answer": "I cannot run shell commands; the expression was rejected."}',
    ])
    res = agent.run("Run rm -rf / on the system")
    assert res.tool_calls[0]["result"]["ok"] is False
    assert "cannot" in res.answer.lower() or "reject" in res.answer.lower()


# --------------------------- max-step enforcement ---------------------------
def test_max_steps_enforced():
    # Model never returns a final answer -> loop must stop at max_steps.
    loop = '{"action": "tool", "tool": "calculate", "arguments": {"expression": "1+1"}}'
    agent, model = make_agent([loop] * 20, max_steps=3)
    res = agent.run("loop forever")
    assert res.exhausted is True
    assert res.steps == 3
    assert len(model.calls) == 3


# --------------------------- invalid model output recovery ---------------------------
def test_invalid_json_then_recovers():
    agent, _ = make_agent([
        "this is not json at all",
        '{"action": "final", "answer": "Recovered."}',
    ])
    res = agent.run("hi")
    assert res.answer == "Recovered."
    assert res.steps == 2


def test_empty_output_then_recovers():
    agent, _ = make_agent([
        "",
        '{"action": "final", "answer": "Recovered from empty."}',
    ])
    res = agent.run("hi")
    assert res.answer == "Recovered from empty."


# --------------------------- tool failure recovery ---------------------------
def test_tool_failure_recovery(ws_subdir):
    name, _ = ws_subdir
    agent, _ = make_agent([
        f'{{"action": "tool", "tool": "read_text_file", "arguments": {{"path": "{name}/missing.txt"}}}}',
        '{"action": "final", "answer": "That file does not exist."}',
    ])
    res = agent.run("Read missing.txt")
    assert res.tool_calls[0]["result"]["ok"] is False
    assert "not exist" in res.answer.lower() or "does not" in res.answer.lower()


# --------------------------- generation error handling ---------------------------
def test_oom_error_is_handled():
    def boom(_messages):
        raise RuntimeError("CUDA out of memory. Tried to allocate ...")
    agent = AgentController(generate_fn=boom, ctx=ToolContext(),
                            logger=security.get_logger("test"))
    res = agent.run("hi")
    assert "memory" in res.answer.lower()
    assert res.error is not None
