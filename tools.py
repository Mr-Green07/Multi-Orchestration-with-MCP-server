"""
tools.py
========
The *fixed* tool registry. The model may only ever call one of these six tools;
it cannot define new ones. Every tool:

  * has a name, description and JSON argument schema,
  * validates its arguments (type + required),
  * enforces the security policy from ``security.py``,
  * returns a uniform ``{"ok": bool, "result"/"error": ...}`` dict,
  * never raises to the caller (errors are captured and returned safely).

Heavy dependencies (faiss / sentence-transformers / fitz) are NOT imported
here -- retrieval is provided through a pre-built ``ctx.retriever`` object, so
this module stays lightweight and unit-testable on its own.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import security as security
from security import (
    MAX_LIST_ENTRIES,
    MAX_FILE_BYTES,
    MAX_OUTPUT_CHARS,
    MAX_SQL_CALLS,
    MAX_SQL_ROWS,
    MAX_TOOL_SECONDS,
    SecurityError,
    TEXT_FILE_EXTENSIONS,
)


class ToolError(Exception):
    """Raised for invalid tool arguments or recoverable tool failures."""


# ---------------------------------------------------------------------------
# Execution context passed to every tool
# ---------------------------------------------------------------------------
@dataclass
class ToolContext:
    """Runtime services available to tools.

    * ``retriever``  -- a retrieval.Retriever (or None if no index is loaded)
    * ``db_path``    -- app-configured, trusted SQLite path (or None)
    * ``confirm``    -- callback(str) -> bool used before overwriting files
    * ``logger``     -- shared logger
    """
    retriever: Any = None
    db_path: Optional[str] = None
    confirm: Callable[[str], bool] = field(default=lambda _msg: False)
    logger: Any = None
    _sql_calls: int = 0

    def reset_counters(self) -> None:
        self._sql_calls = 0


# ---------------------------------------------------------------------------
# Argument-schema validation
# ---------------------------------------------------------------------------
_PY_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    py = _PY_TYPES.get(expected)
    return isinstance(value, py) if py else False


def validate_arguments(schema: Dict[str, dict], arguments: Any) -> Dict[str, Any]:
    """Validate *arguments* against *schema*, returning a clean dict.

    Schema entry format: ``{"type": "string", "required": True, "default": ...}``
    """
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolError("The 'arguments' field must be a JSON object.")

    validated: Dict[str, Any] = {}
    for key, spec in schema.items():
        if key in arguments and arguments[key] is not None:
            value = arguments[key]
            if not _type_ok(value, spec["type"]):
                raise ToolError(f"Argument '{key}' must be of type {spec['type']}.")
            validated[key] = value
        elif spec.get("required"):
            raise ToolError(f"Missing required argument: '{key}'.")
        else:
            validated[key] = spec.get("default")
    return validated


# ---------------------------------------------------------------------------
# Uniform result helpers
# ---------------------------------------------------------------------------
def _ok(result: Any) -> Dict[str, Any]:
    return {"ok": True, "result": result}


def _err(message: str) -> Dict[str, Any]:
    return {"ok": False, "error": message}


# ===========================================================================
# Tool implementations
# ===========================================================================
def _tool_calculate(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    expression = args["expression"]
    try:
        value = security.safe_eval(expression)
    except SecurityError as exc:
        return _err(f"Rejected expression: {exc}")
    except ZeroDivisionError:
        return _err("Division by zero.")
    except (ValueError, OverflowError) as exc:
        return _err(f"Math error: {exc}")
    # Present integers cleanly.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _ok({"expression": expression, "value": value})


def _tool_list_files(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    subdir = args.get("subdir") or "."
    try:
        target = security.resolve_in_workspace(subdir)
    except SecurityError as exc:
        return _err(str(exc))
    if not target.exists():
        return _err(f"Directory not found in workspace: '{subdir}'.")
    if not target.is_dir():
        return _err(f"'{subdir}' is not a directory.")

    entries = []
    for child in sorted(target.iterdir()):
        if child.name == ".gitkeep":
            continue
        try:
            size = child.stat().st_size if child.is_file() else None
        except OSError:
            size = None
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size_bytes": size,
        })
        if len(entries) >= MAX_LIST_ENTRIES:
            break
    rel = target.relative_to(security.WORKSPACE_DIR.resolve())
    return _ok({"directory": str(rel) if str(rel) != "." else "workspace/", "entries": entries})


def _tool_read_text_file(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    path = args["path"]
    try:
        target = security.resolve_in_workspace(path)
    except SecurityError as exc:
        return _err(str(exc))
    if not target.exists():
        return _err(f"File not found in workspace: '{path}'.")
    if not target.is_file():
        return _err(f"'{path}' is not a file.")
    if target.suffix.lower() not in TEXT_FILE_EXTENSIONS:
        return _err(
            f"Refusing to read '{target.suffix}' as text. "
            f"Allowed: {', '.join(sorted(TEXT_FILE_EXTENSIONS))}."
        )
    try:
        size = target.stat().st_size
    except OSError as exc:
        return _err(f"Cannot stat file: {exc}")
    if size > MAX_FILE_BYTES:
        return _err(f"File is too large ({size} bytes; limit {MAX_FILE_BYTES}).")

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _err(f"Failed to read file: {exc}")
    truncated = len(text) > MAX_OUTPUT_CHARS
    return _ok({
        "path": path,
        "truncated": truncated,
        "content": security.truncate(text, MAX_OUTPUT_CHARS),
    })


def _tool_search_documents(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    query = args["query"]
    top_k = args.get("top_k") or 4
    top_k = max(1, min(int(top_k), 10))
    if ctx.retriever is None:
        return _err("No document index is loaded. Build one with build_index.py "
                    "or load it via the CLI '/index' command.")
    try:
        hits = ctx.retriever.search(query, top_k=top_k)
    except Exception as exc:  # retrieval backend errors are surfaced, not raised
        return _err(f"Retrieval failed: {exc}")
    if not hits:
        return _ok({"query": query, "matches": [],
                    "note": "No relevant context found in the indexed documents."})
    matches = [{
        "source": h["source"],
        "chunk_index": h["chunk_index"],
        "score": round(float(h["score"]), 4),
        "text": security.truncate(h["text"], 800),
    } for h in hits]
    return _ok({"query": query, "matches": matches})


def _tool_query_sqlite(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    query = args["query"]

    if ctx._sql_calls >= MAX_SQL_CALLS:
        return _err(f"Too many database calls in one request (limit {MAX_SQL_CALLS}).")
    ctx._sql_calls += 1

    # Resolve which database to use.
    if args.get("db"):
        try:
            db_file = security.resolve_in_dir(args["db"], security.DATABASE_DIR)
        except SecurityError as exc:
            return _err(str(exc))
    elif ctx.db_path:
        db_file = Path(ctx.db_path)
    else:
        return _err("No database selected. Start the agent with --db or pass a 'db' argument.")

    if not Path(db_file).exists():
        return _err(f"Database file not found: '{Path(db_file).name}'.")

    # Validate the SQL is a single read-only statement.
    try:
        clean_sql = security.validate_sql(query)
    except SecurityError as exc:
        return _err(str(exc))

    deadline = time.monotonic() + MAX_TOOL_SECONDS
    conn = None
    try:
        # Read-only connection via URI. as_uri() is correct on both Windows
        # (file:///C:/...) and POSIX (file:///...); as_posix() is not.
        uri = Path(db_file).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=MAX_TOOL_SECONDS)
        conn.row_factory = sqlite3.Row
        # Abort long-running queries.
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
        cur = conn.execute(clean_sql)
        rows = cur.fetchmany(MAX_SQL_ROWS + 1)
        columns = [d[0] for d in cur.description] if cur.description else []
        limited = len(rows) > MAX_SQL_ROWS
        data = [dict(r) for r in rows[:MAX_SQL_ROWS]]
        return _ok({
            "columns": columns,
            "row_count": len(data),
            "truncated": limited,
            "rows": data,
        })
    except sqlite3.OperationalError as exc:
        if "interrupt" in str(exc).lower():
            return _err("Query aborted: exceeded the execution time limit.")
        return _err(f"SQL error: {exc}")
    except sqlite3.DatabaseError as exc:
        return _err(f"Database error: {exc}")
    finally:
        if conn is not None:
            conn.close()


def _tool_create_report(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    filename = security.sanitize_filename(args["filename"])
    title = args.get("title")
    content = args.get("content")
    sections = args.get("sections")

    try:
        target = security.resolve_in_workspace(filename)
    except SecurityError as exc:
        return _err(str(exc))

    # Require explicit confirmation before overwriting.
    if target.exists():
        if not ctx.confirm(f"Report '{filename}' already exists. Overwrite it?"):
            return _err(f"Report '{filename}' already exists; overwrite was not confirmed.")

    # Build the document body.
    lines = []
    if title:
        lines.append(f"# {title}\n")
    if content:
        lines.append(str(content).strip() + "\n")
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict):
                heading = sec.get("heading") or sec.get("title")
                body = sec.get("body") or sec.get("content") or ""
                if heading:
                    lines.append(f"\n## {heading}\n")
                if body:
                    lines.append(str(body).strip() + "\n")
            else:
                lines.append(str(sec) + "\n")
    if not lines:
        return _err("Nothing to write: provide 'content' and/or 'sections'.")

    document = "\n".join(lines).strip() + "\n"
    try:
        target.write_text(document, encoding="utf-8")
    except OSError as exc:
        return _err(f"Failed to write report: {exc}")

    rel = target.relative_to(security.WORKSPACE_DIR.resolve())
    return _ok({"saved_to": f"workspace/{rel.as_posix()}", "bytes": len(document.encode("utf-8"))})


# ===========================================================================
# Tool descriptors + registry
# ===========================================================================
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: Dict[str, dict]
    func: Callable[[Dict[str, Any], ToolContext], Dict[str, Any]]


TOOLS: Dict[str, Tool] = {
    "calculate": Tool(
        name="calculate",
        description="Evaluate a safe arithmetic expression (e.g. '25 * 4', 'sqrt(2) + log(10)').",
        schema={"expression": {"type": "string", "required": True}},
        func=_tool_calculate,
    ),
    "list_files": Tool(
        name="list_files",
        description="List files and folders inside the workspace/ directory.",
        schema={"subdir": {"type": "string", "required": False, "default": "."}},
        func=_tool_list_files,
    ),
    "read_text_file": Tool(
        name="read_text_file",
        description="Read a UTF-8 text file located inside workspace/.",
        schema={"path": {"type": "string", "required": True}},
        func=_tool_read_text_file,
    ),
    "search_documents": Tool(
        name="search_documents",
        description="Semantic search over locally indexed documents; returns top-k relevant chunks with sources.",
        schema={
            "query": {"type": "string", "required": True},
            "top_k": {"type": "integer", "required": False, "default": 4},
        },
        func=_tool_search_documents,
    ),
    "query_sqlite": Tool(
        name="query_sqlite",
        description="Run a single read-only SQL query (SELECT / PRAGMA) against the local SQLite database.",
        schema={
            "query": {"type": "string", "required": True},
            "db": {"type": "string", "required": False},
        },
        func=_tool_query_sqlite,
    ),
    "create_report": Tool(
        name="create_report",
        description="Write a Markdown/text report into workspace/. Requires confirmation to overwrite.",
        schema={
            "filename": {"type": "string", "required": True},
            "title": {"type": "string", "required": False},
            "content": {"type": "string", "required": False},
            "sections": {"type": "array", "required": False},
        },
        func=_tool_create_report,
    ),
}


def tool_names() -> list:
    return list(TOOLS.keys())


def describe_tools() -> str:
    """Human/LLM-readable description of the registry (used in the system prompt)."""
    out = []
    for i, tool in enumerate(TOOLS.values(), start=1):
        required = [k for k, s in tool.schema.items() if s.get("required")]
        optional = [k for k, s in tool.schema.items() if not s.get("required")]
        arg_bits = []
        for k, s in tool.schema.items():
            tag = "required" if s.get("required") else "optional"
            arg_bits.append(f"{k}:{s['type']} ({tag})")
        out.append(
            f"{i}. {tool.name} - {tool.description}\n"
            f"   arguments: {{ {', '.join(arg_bits) if arg_bits else 'none'} }}"
        )
    return "\n".join(out)


def run_tool(name: str, arguments: Any, ctx: ToolContext) -> Dict[str, Any]:
    """Validate + execute a tool by *name*, enforcing a wall-clock timeout.

    Never raises: any failure is returned as ``{"ok": False, "error": ...}``.
    """
    if name not in TOOLS:
        return _err(f"Unknown tool '{name}'. Available tools: {', '.join(TOOLS)}.")
    tool = TOOLS[name]

    try:
        clean_args = validate_arguments(tool.schema, arguments)
    except ToolError as exc:
        return _err(str(exc))

    import threading

    holder: Dict[str, Any] = {}

    def _target():
        try:
            holder["value"] = tool.func(clean_args, ctx)
        except SecurityError as exc:
            holder["value"] = _err(f"Security policy violation: {exc}")
        except Exception as exc:  # defensive: never let a tool crash the agent
            holder["value"] = _err(f"Tool '{name}' raised an unexpected error: {exc}")

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(MAX_TOOL_SECONDS + 1.0)  # +1s grace over the tool's own budget
    if thread.is_alive():
        return _err(f"Tool '{name}' timed out after {MAX_TOOL_SECONDS} seconds.")
    return holder.get("value", _err(f"Tool '{name}' returned no result."))


def result_to_text(result: Dict[str, Any]) -> str:
    """Compact, size-capped string form of a tool result for the model."""
    try:
        payload = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = str(result)
    return security.truncate(payload, MAX_OUTPUT_CHARS)
