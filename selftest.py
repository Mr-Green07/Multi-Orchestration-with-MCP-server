"""
selftest.py
===========
Zero-dependency smoke test (standard library only -- no pytest, no torch).

Because the whole point of this project is OFFLINE operation (where even
`pip install pytest` may be unavailable), this script lets you verify the core
safety and control logic immediately:

    python selftest.py

It exercises the calculator sandbox, path validation, read-only SQL
enforcement, strict-JSON parsing, the tool registry, and a full scripted
agent run. For the complete, richer suite use pytest (see README > Testing).
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import security
import tools
from tools import ToolContext, run_tool
from agent_controller import AgentController, extract_json, validate_action

PASS = 0
FAIL = 0


def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def expect_security_error(fn, *args):
    try:
        fn(*args)
        return False
    except security.SecurityError:
        return True
    except Exception:
        return False


class ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
    def __call__(self, messages):
        return self.responses.pop(0) if self.responses else '{"action":"final","answer":"done"}'


def main():
    print("== calculator sandbox ==")
    check("25 * 4 == 100", security.safe_eval("25 * 4") == 100)
    check("sqrt(16) == 4", security.safe_eval("sqrt(16)") == 4)
    check("rejects __import__", expect_security_error(security.safe_eval, "__import__('os')"))
    check("rejects attribute access", expect_security_error(security.safe_eval, "(1).__class__"))
    check("rejects lambda", expect_security_error(security.safe_eval, "lambda: 1"))
    check("rejects huge exponent", expect_security_error(security.safe_eval, "2 ** 100000"))

    print("== path validation ==")
    check("rejects ..", expect_security_error(security.resolve_in_workspace, "../secret.txt"))
    check("rejects absolute", expect_security_error(security.resolve_in_workspace, "/etc/passwd"))
    check("accepts normal path",
          str(security.resolve_in_workspace("notes.txt")).endswith("notes.txt"))

    print("== read-only SQL ==")
    check("allows SELECT", bool(security.validate_sql("SELECT * FROM t")))
    check("rejects DELETE", expect_security_error(security.validate_sql, "DELETE FROM t"))
    check("rejects multi-statement", expect_security_error(security.validate_sql, "SELECT 1; DROP TABLE t"))

    print("== strict JSON ==")
    obj, err = extract_json('noise {"action":"final","answer":"hi"} trailing')
    check("extracts embedded JSON", obj is not None and obj["answer"] == "hi")
    kind, _p, _e = validate_action({"action": "tool", "tool": "calculate", "arguments": {}})
    check("validates tool action", kind == "tool")
    _k, _p, verr = validate_action({"action": "banana"})
    check("rejects bad action", verr is not None)

    print("== tool registry ==")
    r = run_tool("calculate", {"expression": "6*7"}, ToolContext())
    check("calculate tool -> 42", r["ok"] and r["result"]["value"] == 42)
    r = run_tool("read_text_file", {"path": "../tools.py"}, ToolContext())
    check("file tool blocks traversal", not r["ok"])
    r = run_tool("nope", {}, ToolContext())
    check("unknown tool rejected", not r["ok"])

    print("== sqlite tool (read-only) ==")
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.executemany("INSERT INTO t VALUES (?,?)", [(1, "a"), (2, "b")])
        conn.commit(); conn.close()
        ctx = ToolContext(db_path=str(db))
        r = run_tool("query_sqlite", {"query": "SELECT COUNT(*) AS n FROM t"}, ctx)
        check("SELECT works", r["ok"] and r["result"]["rows"][0]["n"] == 2)
        r = run_tool("query_sqlite", {"query": "DROP TABLE t"}, ctx)
        check("DROP blocked", not r["ok"])

    print("== end-to-end agent (scripted model) ==")
    agent = AgentController(
        generate_fn=ScriptedModel([
            '{"action":"tool","tool":"calculate","arguments":{"expression":"25 * 4"}}',
            '{"action":"final","answer":"25 times 4 equals 100."}',
        ]),
        ctx=ToolContext(),
        logger=security.get_logger("selftest"),
    )
    res = agent.run("What is 25 * 4?")
    check("tool was called", res.tool_calls and res.tool_calls[0]["tool"] == "calculate")
    check("final answer correct", "100" in res.answer)

    agent2 = AgentController(
        generate_fn=ScriptedModel(['{"action":"tool","tool":"calculate","arguments":{"expression":"1+1"}}'] * 10),
        ctx=ToolContext(), logger=security.get_logger("selftest"), max_steps=3,
    )
    res2 = agent2.run("loop")
    check("max-step limit enforced", res2.exhausted and res2.steps == 3)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
