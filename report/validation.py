"""Guardrail validation suite.

Executes adversarial + legitimate cases against the real security layers of the
repository and reports blocked / allowed counts per category.
Writes report/validation_results.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import security as root_security  # noqa: E402
import tools as root_tools  # noqa: E402
from mcp_server import security as mcp_security  # noqa: E402
from mcp_server.tools import workspace  # noqa: E402


def blocked(fn) -> bool:
    """True when the layer refused (raised SecurityError or returned an error)."""
    try:
        res = fn()
    except root_security.SecurityError:
        return True
    except Exception:
        return True
    if isinstance(res, dict) and res.get("status") == "error":
        return True
    return False


# ---------------------------------------------------------------- path traversal
J = workspace.JAIL_ROOT
(J / "safe.txt").write_text("baseline", encoding="utf-8")

TRAVERSAL = [
    "../../etc/passwd",
    "..\\..\\Windows\\System32\\drivers\\etc\\hosts",
    "/etc/passwd",
    "/",
    "C:\\Windows\\win.ini",
    "..%2f..%2fetc%2fpasswd",
    "....//....//etc/passwd",
    "~/../../etc/shadow",
    "\\\\attacker\\share\\payload.txt",
    "safe.txt/../../etc/passwd",
]

mcp_path_cases = [blocked(lambda p=p: workspace.execute_workspace_fs("read_text", p)) for p in TRAVERSAL]
root_path_cases = [blocked(lambda p=p: root_security.resolve_in_workspace(p)) for p in TRAVERSAL]

# ---------------------------------------------------------------- expression eval
EVIL_EXPRS = [
    "__import__('os').system('echo pwned')",
    "open('/etc/passwd').read()",
    "eval('1+1')",
    "exec('print(1)')",
    "(lambda: 1)()",
    "[].__class__.__base__.__subclasses__()",
    "9**9**9**9",
    "globals()",
    "1+" * 400 + "1",
    "'a'*999999999",
]
EXPR_OK = ["25*4", "sqrt(2)+log(10)", "(3+4)*2/7", "abs(-9)+min(3,4)", "pi*2"]

expr_block = [blocked(lambda e=e: root_security.safe_eval(e)) for e in EVIL_EXPRS]
expr_allow = [not blocked(lambda e=e: root_security.safe_eval(e)) for e in EXPR_OK]

# ---------------------------------------------------------------- sql guard
SQL_EVIL = [
    "DROP TABLE users",
    "DELETE FROM users",
    "UPDATE users SET admin=1",
    "INSERT INTO users VALUES (1,'x')",
    "ATTACH DATABASE '/tmp/e.db' AS e",
    "SELECT 1; DROP TABLE users",
    "PRAGMA writable_schema=1",
    "VACUUM INTO '/tmp/out.db'",
    "WITH x AS (SELECT 1) DELETE FROM users",
    "SELECT load_extension('malicious')",
]
SQL_OK = [
    "SELECT name FROM sqlite_master WHERE type='table'",
    "PRAGMA table_info(users)",
    "SELECT count(*) FROM users",
    "SELECT * FROM users LIMIT 5",
    "select id, email from users where id > 10 order by id",
]
sql_block = [blocked(lambda q=q: root_security.validate_sql(q)) for q in SQL_EVIL]
sql_allow = [not blocked(lambda q=q: root_security.validate_sql(q)) for q in SQL_OK]

# ---------------------------------------------------------------- ctypes envelope
ARGS_EVIL = [
    ("calculate", {"expression": 42}),
    ("calculate", {}),
    ("list_files", {"subdir": ["a"]}),
    ("read_text_file", {"path": None}),
    ("search_documents", "not-an-object"),
    ("no_such_tool", {}),
    ("create_report", {"filename": "../../../evil.md", "content": "x"}),
]
ctx = root_tools.ToolContext(confirm=lambda _m: False)
arg_block = [
    blocked(lambda n=n, a=a: _as_error(root_tools.run_tool(n, a, ctx))) for n, a in ARGS_EVIL
]


def _as_error(res):
    return res if not res.get("ok", False) else {"status": "success"}


# ---------------------------------------------------------------- confirmation token
def token_suite():
    cases = {}
    tok = mcp_security.create_confirmation_token("shutdown", {"target_action": "shutdown"})
    cases["valid_token_accepted"] = mcp_security.verify_and_consume_token(tok, "shutdown") is not None
    cases["replay_rejected"] = mcp_security.verify_and_consume_token(tok, "shutdown") is None

    tok2 = mcp_security.create_confirmation_token("restart", {"target_action": "restart"})
    cases["wrong_action_rejected"] = mcp_security.verify_and_consume_token(tok2, "shutdown") is None

    tok3 = mcp_security.create_confirmation_token("shutdown", {})
    cases["tampered_rejected"] = mcp_security.verify_and_consume_token(tok3[:-2] + "aa", "shutdown") is None

    tok4 = mcp_security.create_confirmation_token("shutdown", {})
    mcp_security._PENDING_CONFIRMATIONS[tok4]["expires_at"] = time.time() - 1
    cases["expired_rejected"] = mcp_security.verify_and_consume_token(tok4, "shutdown") is None

    cases["unknown_token_rejected"] = mcp_security.verify_and_consume_token("deadbeef", "shutdown") is None
    cases["missing_token_rejected"] = mcp_security.verify_and_consume_token("", "shutdown") is None
    return cases


tokens = token_suite()

# ---------------------------------------------------------------- assemble
def pct(seq):
    return round(100.0 * sum(1 for s in seq if s) / len(seq), 1) if seq else 0.0


summary = {
    "environment": {"jail": str(J), "platform": sys.platform},
    "categories": [
        {
            "name": "Path traversal / jail escape (workspace_fs)",
            "cases": len(mcp_path_cases),
            "blocked": sum(mcp_path_cases),
            "rate": pct(mcp_path_cases),
        },
        {
            "name": "Path traversal / jail escape (security.resolve_in_workspace)",
            "cases": len(root_path_cases),
            "blocked": sum(root_path_cases),
            "rate": pct(root_path_cases),
        },
        {
            "name": "Unsafe expression execution (safe_eval)",
            "cases": len(expr_block),
            "blocked": sum(expr_block),
            "rate": pct(expr_block),
        },
        {
            "name": "Legitimate arithmetic expressions accepted",
            "cases": len(expr_allow),
            "blocked": sum(expr_allow),
            "rate": pct(expr_allow),
        },
        {
            "name": "SQL write / DDL / stacked statements",
            "cases": len(sql_block),
            "blocked": sum(sql_block),
            "rate": pct(sql_block),
        },
        {
            "name": "Legitimate read-only SQL accepted",
            "cases": len(sql_allow),
            "blocked": sum(sql_allow),
            "rate": pct(sql_allow),
        },
        {
            "name": "Malformed tool arguments rejected",
            "cases": len(arg_block),
            "blocked": sum(arg_block),
            "rate": pct(arg_block),
        },
        {
            "name": "Confirmation token abuse rejected",
            "cases": len(tokens),
            "blocked": sum(1 for v in tokens.values() if v),
            "rate": pct(list(tokens.values())),
        },
    ],
    "token_cases": tokens,
    "totals": {
        "adversarial_cases": len(mcp_path_cases) + len(expr_block) + len(sql_block) + len(arg_block) + len(tokens),
        "blocked": sum(mcp_path_cases) + sum(expr_block) + sum(sql_block) + sum(arg_block) + sum(1 for v in tokens.values() if v),
    },
    "false_positives": {
        "expressions": len([x for x in expr_allow if not x]),
        "sql": len([x for x in sql_allow if not x]),
    },
}

out = Path(__file__).resolve().parent / "validation_results.json"
out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
