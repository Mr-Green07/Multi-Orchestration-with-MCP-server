"""
security.py
===========
Central security policy for the offline agent.

Everything that could be dangerous is funnelled through this module:

* Filesystem sandboxing (workspace-only, no traversal, no absolute paths).
* A safe arithmetic evaluator built on the `ast` module (NO eval/exec).
* Read-only SQL validation.
* Global limits (steps, output size, timeouts, row caps, ...).
* Structured logging of every request / model response / tool call / result.

This module intentionally has *no* heavy third-party imports so it can be
imported (and unit-tested) without torch/transformers/faiss installed.
"""

from __future__ import annotations

import ast
import logging
import math
import operator
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Directory layout (all paths are relative to this file)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
DOCUMENTS_DIR = BASE_DIR / "documents"
INDEXES_DIR = BASE_DIR / "indexes"
DATABASE_DIR = BASE_DIR / "database"
LOGS_DIR = BASE_DIR / "logs"
MODELS_DIR = BASE_DIR / "models"
ADAPTERS_DIR = BASE_DIR / "adapters"

for _d in (WORKSPACE_DIR, DOCUMENTS_DIR, INDEXES_DIR, DATABASE_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Global limits / policy knobs
# ---------------------------------------------------------------------------
MAX_STEPS = 4                 # hard cap on agent reasoning steps
MAX_OUTPUT_CHARS = 4000       # cap on any tool result fed back to the model
MAX_TOOL_SECONDS = 5.0        # wall-clock timeout per tool call
MAX_FILE_BYTES = 1_000_000    # 1 MB cap when reading a text file
MAX_EXPR_LEN = 500            # calculator expression length cap
MAX_POW_EXPONENT = 1000       # reject huge exponents (DoS guard)
MAX_LIST_ENTRIES = 500        # cap for list_files
MAX_SQL_LEN = 2000            # SQL query length cap
MAX_SQL_ROWS = 100            # max rows returned by query_sqlite
MAX_SQL_CALLS = 5             # max db calls per user request
MAX_MODEL_NEW_TOKENS = 384    # generation cap (also guards context blow-up)

# File extensions the agent is allowed to read as text.
TEXT_FILE_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json",
    ".log", ".yaml", ".yml", ".ini", ".cfg", ".py", ".rst",
}


class SecurityError(Exception):
    """Raised whenever a security policy is violated."""


# ---------------------------------------------------------------------------
# Filesystem sandbox
# ---------------------------------------------------------------------------
def resolve_in_dir(user_path: str, base: Path) -> Path:
    """Resolve *user_path* inside *base*, refusing any escape.

    Blocks:
      * ``None``/non-string input
      * absolute paths (POSIX ``/...``, Windows ``C:\\``, UNC ``\\\\host``)
      * ``..`` traversal in any segment
      * symlink / normalization escapes (verified after ``resolve()``)
    """
    if user_path is None or not isinstance(user_path, str):
        raise SecurityError("A string path is required.")

    raw = user_path.strip()
    if raw == "":
        raw = "."

    # Reject absolute paths of every flavour.
    if os.path.isabs(raw) or re.match(r"^[A-Za-z]:", raw) or raw.startswith("\\\\"):
        raise SecurityError("Absolute paths are not allowed; use a path inside the workspace.")

    # Reject explicit parent-directory traversal.
    segments = re.split(r"[\\/]+", raw)
    if any(seg == ".." for seg in segments):
        raise SecurityError("Path traversal ('..') is not allowed.")

    base_resolved = base.resolve()
    candidate = (base_resolved / raw).resolve()

    # Final containment check (also catches symlink escapes).
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise SecurityError("Path escapes the approved directory.")
    return candidate


def resolve_in_workspace(user_path: str) -> Path:
    """Convenience wrapper: resolve a path inside ``workspace/``."""
    return resolve_in_dir(user_path, WORKSPACE_DIR)


def sanitize_filename(name: str) -> str:
    """Reduce *name* to a safe base filename (no directories, safe chars).

    Ensures a ``.md`` or ``.txt`` extension so reports always land as text.
    """
    if not isinstance(name, str) or not name.strip():
        return "report.md"
    base = os.path.basename(name.strip())          # strip any directory part
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)    # allowlist characters
    base = base.strip("._") or "report"
    if not base.lower().endswith((".md", ".txt")):
        base += ".md"
    return base


# ---------------------------------------------------------------------------
# Safe calculator  (AST based -- no eval / exec / imports / attributes)
# ---------------------------------------------------------------------------
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCS = {
    name: getattr(math, name)
    for name in (
        "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "sinh", "cosh", "tanh", "log", "log2", "log10", "exp",
        "floor", "ceil", "fabs", "factorial", "degrees", "radians",
        "hypot", "gcd", "trunc",
    )
}
_ALLOWED_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max})
_ALLOWED_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_eval(expression: str):
    """Safely evaluate an arithmetic *expression*.

    Supports +, -, *, /, //, %, ** and a whitelist of math functions and
    constants. Rejects imports, attribute access, subscripts, comprehensions,
    names outside the whitelist, and everything else by construction.
    """
    if not isinstance(expression, str):
        raise SecurityError("Expression must be a string.")
    if len(expression) > MAX_EXPR_LEN:
        raise SecurityError("Expression is too long.")
    if not expression.strip():
        raise SecurityError("Empty expression.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SecurityError(f"Invalid expression syntax: {exc.msg}")
    return _eval_node(tree.body)


def _eval_node(node):
    if isinstance(node, ast.Constant):
        # bool is a subclass of int -- reject it and any non-number.
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise SecurityError("Only numeric constants are allowed.")
        return node.value

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BINOPS:
            raise SecurityError(f"Operator '{op_type.__name__}' is not allowed.")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op_type is ast.Pow and isinstance(right, (int, float)) and abs(right) > MAX_POW_EXPONENT:
            raise SecurityError("Exponent is too large.")
        return _ALLOWED_BINOPS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_UNARY:
            raise SecurityError("This unary operator is not allowed.")
        return _ALLOWED_UNARY[op_type](_eval_node(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise SecurityError("Only direct calls to allowed functions are permitted.")
        fname = node.func.id
        if fname not in _ALLOWED_FUNCS:
            raise SecurityError(f"Function '{fname}' is not allowed.")
        if node.keywords:
            raise SecurityError("Keyword arguments are not allowed.")
        args = [_eval_node(a) for a in node.args]
        return _ALLOWED_FUNCS[fname](*args)

    if isinstance(node, ast.Name):
        if node.id not in _ALLOWED_NAMES:
            raise SecurityError(f"Unknown name '{node.id}'.")
        return _ALLOWED_NAMES[node.id]

    # Anything else (Attribute, Subscript, Lambda, comprehensions, ...) is rejected.
    raise SecurityError(f"Disallowed expression element: {type(node).__name__}")


# ---------------------------------------------------------------------------
# Read-only SQL validation
# ---------------------------------------------------------------------------
_SQL_ALLOWED_STARTS = {"select", "pragma", "with", "explain"}
_SQL_FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "attach",
    "detach", "replace", "truncate", "reindex", "vacuum", "grant", "revoke",
    "commit", "rollback", "savepoint",
)


def validate_sql(query: str) -> str:
    """Validate that *query* is a single, read-only SQL statement.

    Returns the cleaned statement (comments stripped, trailing ``;`` removed)
    or raises :class:`SecurityError`.
    """
    if not isinstance(query, str):
        raise SecurityError("SQL query must be a string.")
    stripped_raw = query.strip()
    if not stripped_raw:
        raise SecurityError("Empty SQL query.")
    if len(stripped_raw) > MAX_SQL_LEN:
        raise SecurityError("SQL query is too long.")

    # Remove -- line comments and /* block comments */.
    no_comments = re.sub(r"--[^\n]*", " ", stripped_raw)
    no_comments = re.sub(r"/\*.*?\*/", " ", no_comments, flags=re.DOTALL)
    cleaned = no_comments.strip().rstrip(";").strip()
    if not cleaned:
        raise SecurityError("Empty SQL query after removing comments.")

    # Disallow multiple statements.
    if ";" in cleaned:
        raise SecurityError("Multiple SQL statements are not allowed.")

    lowered = cleaned.lower()
    first_kw_match = re.match(r"[a-z_]+", lowered)
    if not first_kw_match or first_kw_match.group(0) not in _SQL_ALLOWED_STARTS:
        raise SecurityError("Only SELECT / PRAGMA / WITH / EXPLAIN queries are allowed.")

    for kw in _SQL_FORBIDDEN:
        if re.search(rf"\b{kw}\b", lowered):
            raise SecurityError(f"Forbidden SQL keyword: {kw.upper()}")

    return cleaned


# ---------------------------------------------------------------------------
# Logging  (every request / response / tool call / result is recorded)
# ---------------------------------------------------------------------------
def get_logger(name: str = "offline_agent", debug: bool = False,
               to_console: bool = False) -> logging.Logger:
    """Return a configured, idempotent logger writing to ``logs/agent.log``."""
    logger = logging.getLogger(name)
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            LOGS_DIR / "agent.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)

    if to_console and not any(isinstance(h, logging.StreamHandler)
                              and not isinstance(h, RotatingFileHandler)
                              for h in logger.handlers):
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        ch.setLevel(logging.DEBUG)
        logger.addHandler(ch)

    logger.propagate = False
    return logger


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate *text* to *limit* characters with an explicit marker."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"
